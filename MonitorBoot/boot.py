#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import datetime
import os
import time
import uuid
from asyncio import coroutines
import psutil
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyutilb.asyncio_threadpool import get_running_loop
from pyutilb.strs import substr_after, substr_before
from pyutilb.tail import Tail
from pyutilb.util import *
from pyutilb.file import *
from pyutilb.cmd import *
from pyutilb import YamlBoot, EventLoopThreadPool, ts
from pyutilb.log import log
from MonitorBoot import emailer
from MonitorBoot.alert_examiner import AlertException, AlertExaminer
from MonitorBoot.gc_log_parser import GcLogParser
from MonitorBoot.procinfo import ProcInfo
from MonitorBoot.procstat import all_proc_stat2xlsx
from MonitorBoot.sysinfo import SysInfo

# 协程线程池
pool = EventLoopThreadPool(1)

# 基于yaml的监控器
class MonitorBoot(YamlBoot):

    def __init__(self):
        super().__init__()
        # 动作映射函数
        actions = {
            'config_email': self.config_email,
            'send_email': self.send_email,
            'schedule': self.schedule,
            'tail': self.tail,
            'alert': self.alert,
            'when_alert': self.when_alert,
            'send_alert_email': self.send_alert_email,
            'monitor_pid': self.monitor_pid,
            'grep_pid': self.grep_pid,
            'monitor_gc_log': self.monitor_gc_log,
            # 异步动作
            'dump_jvm_heap': self.dump_jvm_heap,
            'dump_jvm_thread': self.dump_jvm_thread,
            'dump_jvm_gcs_xlsx': self.dump_jvm_gcs_xlsx,
            'dump_all_proc_xlsx': self.dump_all_proc_xlsx,
            'dump_sys_csv': self.dump_sys_csv,
            'dump_1proc_csv': self.dump_1proc_csv,
            'compare_gc_logs': self.compare_gc_logs,
            # 结束
            'stop_after': self.stop_after,
            'stop_at': self.stop_at,
        }
        self.add_actions(actions)

        # 创建调度器: 抄 SchedulerThread 的实现
        self.loop = asyncio.get_event_loop()
        self.scheduler = AsyncIOScheduler()
        self.scheduler._eventloop = self.loop  # 调度器的loop = 线程的loop, 否则线程无法处理调度器的定时任务
        self.scheduler.start()

        # tail跟踪
        self.tails = {}

        # gc日志解析器，只支持解析单个日志，没必要支持解析多个日志
        self.gc_parser = None

        # 进程信息
        self._pid = None
        self._pid_grep = None
        self._proc = None

        # ----- 告警处理 -----
        # 告警条件的检查者
        self.alert_examiner = AlertExaminer(self)

        # 记录告警条件的过期时间, key是告警条件(表示类型), value是过期时间，没过期就不处理告警，用来限制同条件的告警的处理频率，如限制导出进程xlsx或发邮件
        self.alert_condition_expires = {}

    # 执行完的后置处理
    def on_end(self):
        # 死循环处理s
        self.loop.run_forever()

    # -------------------------------- 普通动作 -----------------------------------
    # 睡眠
    async def sleep(self, seconds):
        if get_running_loop() is None:
            time.sleep(int(seconds))
        else:
            await asyncio.sleep(int(seconds))

    # 执行命令
    async def exec(self, cmd):
        # wait_output = False 用于在 when_not_run 中调用 exec() 重启被监控的进程，但又不能因为启动进程的命令执行而阻塞当前线程
        await run_command_async(cmd, wait_output = False)

    # 配置邮件服务器
    # :param config 包含host, password, from_name, from_email, to_name, to_email
    def config_email(self, config):
        config = replace_var(config, False)
        emailer.config_email(config)

    # 发送邮件
    def send_email(self, params):
        self.do_send_email(params['title'], params['msg'])

    # 真正的发邮件
    def do_send_email(self, title, msg):
        if self.debug:
            log.info(f"----- 调试模式下模拟发邮件: title = %s, msg = %s -----", title, msg)
            return
        try:
            emailer.send_email(title, msg)
        except Exception as ex:
            log.error("MonitorBoot.do_send_email()异常: " + str(ex), exc_info=ex)

    async def run_steps_async(self, steps, vars = {}, serial = True):
        '''
        异步执行步骤
            主要是优化 psutil.cpu_percent(1) 的阻塞 + when_alert 耗时操作 所带来的性能问题，要扔到eventloop所在的线程中运行
            因为要扔到其他线程执行，导致不能直接使用调用线程的变量，因此需要通过 vars 参数来传递
        :param steps: 要执行的步骤
        :param vars: 传递调用线程中的变量
        :param serial: 是否串行执行，否则并行执行(一般用于执行 when_alert 耗时操作)
        :return:
        '''
        # 提前预备好SysInfo
        vars['sys'] = await SysInfo().presleep_fields_in_steps(steps)

        # 应用变量，因为变量是在ThreadLocal中，只能在同步代码中应用
        with UseVars(vars):
            # 真正执行步骤
            if serial: # 串行
                await self.run_steps_serial(steps)
            else: # 并行
                await self.run_steps_parallel(steps)

    # 串行执行多个步骤
    async def run_steps_serial(self, steps):
        # 逐个步骤调用多个动作
        for step in steps:
            self.stat.incr_step()  # 统计
            for action, param in step.items():
                self.stat.incr_action()  # 统计
                ret = self.run_action(action, param)
                # 如果返回值是协程, 则要await
                if coroutines.iscoroutine(ret):
                    await ret

    #  并行执行多个步骤
    async def run_steps_parallel(self, steps):
        # 收集异步结果
        async_rets  = []
        # 逐个步骤调用多个动作
        for step in steps:
            self.stat.incr_step()  # 统计
            for action, param in step.items():
                self.stat.incr_action()  # 统计
                ret = self.run_action(action, param)
                # 如果返回值是协程, 则要await
                if coroutines.iscoroutine(ret):
                    async_rets.append(ret)
        # 等待所有结果
        await asyncio.gather(async_rets)

    def schedule(self, steps, wait_seconds):
        '''
        定时器
        :param steps: 每次定时要执行的步骤
        :param wait_seconds: 时间间隔,单位秒
        :return:
        '''
        self.scheduler.add_job(self.run_steps_async, 'interval', args=(steps,), seconds=int(wait_seconds), next_run_time=datetime.datetime.now())

    def tail(self, steps, file):
        '''
        监控文件内容追加，常用于订阅日志变更
           变量 tail_line 记录读到的行
        :param steps: 每次定时要执行的步骤
        :param file: 文件路径
        :return:
        '''
        async def read_line(line):
            # 将行塞到变量中，以便子步骤能读取
            vars = {'tail_line': line}
            # 执行子步骤
            await self.run_steps_async(steps, vars)
        self.do_tail(file, read_line)

    def do_tail(self, file, callback):
        '''
        监控文件内容追加，常用于订阅日志变更
        :param file: 文件路径
        :param callback: 回调
        :return:
        '''
        t = Tail(file, self.scheduler)
        self.tails[file] = t
        t.follow(callback)

    # -------------------------------- 告警的动作 -----------------------------------
    # ThreadLocal记录当发生告警要调用的动作
    # 必须在 alert() 动作前调用
    def when_alert(self, steps):
        set_var('when_alert', steps)

    async def alert(self, conditions, expire_sec = 600):
        '''
        告警处理
        :param conditions: 多个告警条件
        :param expire_sec: 同条件的告警的过期秒数(默认600秒)，没过期就不处理同条件告警，用于限制同条件的告警的处理频率
        :return:
        '''
        if not isinstance(conditions, (str, list)):
            raise Exception("告警参数必须str或list类型")
        if isinstance(conditions, str):
            conditions = [conditions]

        try:
            # 1 逐个表达式来执行告警，如果报警发生则报异常
            for condition in conditions:
                condition = condition.lstrip()
                self.alert_examiner.run(condition)
        except AlertException as ex:
            # 2 处理告警异常：异常=告警发生
            await self.handle_alert_exception(ex, int(expire_sec))

    async def handle_alert_exception(self, ex: AlertException, expire_sec):
        '''
        处理告警异常：异常=告警发生
        :param condition: 告警条件
        :param ex: 告警异常
        :param expire_sec: 同条件的告警的过期秒数(默认600秒)，没过期就不处理同条件告警，用于限制同条件的告警的处理频率
        :return:
        '''
        msg = str(ex)
        log.error(msg)

        # 检查该条件的告警是否没过期, 是的话就不处理同条件(同类)异常
        condition = ex.condition
        if not self.check_alert_expired(condition, expire_sec):
            if condition in self.alert_condition_expires:
                print("过期时间为: "+ ts.timestamp2str(self.alert_condition_expires[condition]))
            log.info(f"在%s秒内忽略同条件[%s]的告警", expire_sec, condition)
            return

        # 处理告警异常
        # 当发生告警异常要调用when_alert注册的动作
        steps = get_var('when_alert')
        set_var('when_alert', None)
        if steps:
            log.info("告警发生, 触发when_alert注册的动作")
            # 用告警条件来做告警目录，以便后续放置dump文件
            now = ts.now2str("%Y%m%d%H%M%S")
            dir = f"alert[{condition.replace(' ', '')}]-{now}"
            os.mkdir(dir)
            vars = {
                'alert_msg': msg,
                'alert_dir': dir,
            }
            # 执行when_alert动作
            # await self.run_steps_async(steps, vars)
            pool.exec(self.run_steps_async, steps, vars) # 耗时操作扔到线程池执行

    def check_alert_expired(self, condition, expire_sec):
        '''
        检查该条件的告警是否过期
        :param condition: 告警条件
        :param expire_sec: 同条件的告警的过期秒数(默认600秒)，没过期就不处理同条件告警，用于限制同条件的告警的处理频率
        :return:
        '''
        now = time.time()
        # 没过期时间(之前没发生过同条件告警) or 过期了
        ret = condition not in self.alert_condition_expires \
                or self.alert_condition_expires[condition] < now  # 过期了

        # 过期后，要更新过期时间
        if ret:
            self.alert_condition_expires[condition] = now + expire_sec
        return ret

    # 发送告警邮件
    def send_alert_email(self, _):
        # 发邮件
        msg = get_var('alert_msg')
        if ':' in msg:
            title = substr_before(msg, ': ')
        else:
            title = msg
        # alert_dir = os.getcwd()
        alert_dir = os.path.abspath(get_var('alert_dir'))
        msg = msg + "\n详细日志与导出文件在目录: " + alert_dir
        self.do_send_email(title, msg)

    # -------------------------------- 监控进程 -----------------------------------
    # 监控的进程id
    @property
    def pid(self):
        if self._pid is None:
            self.grep_pid(self._pid_grep) # 先尝试grep pid
            if self._pid is None:
                raise Exception("没用使用动作 monitor_pid/grep_pid 来监控 pid")
        return self._pid

    # 监控的进程名
    @property
    def pname(self):
        if self._proc is None:
            self.grep_pid(self._pid_grep) # 先尝试grep pid
        return self._proc.name

    # 检查是否监控java进程
    def check_moniter_java(self, action):
        if self._pid is None:
            raise Exception("无pid")
        if not self._proc.is_java:
            pname = f"{self.pname}[{self.pid}]"
            raise Exception(f"非java进程: {pname}, 不能执行{action}")

    def monitor_pid(self, options):
        '''
        监控进程，如果进程不存在，则抛异常
        :param options 选项，包含
                    grep: 用ps aux搜索进程时要搜索的关键字
                    interval: 定时检查的时间间隔，用于定时检查进程是否还存在，默认10秒
                    when_no_run: 当进程没运行时执行的步骤
        :return:
        '''
        # 1 使用 ps aux | grep 来获得pid
        try:
            self.grep_pid(options['grep'])
        except Exception as ex:
            # 2 当进程没运行时执行的步骤
            steps = options.get('when_no_run')
            if steps is not None:
                log.info(f"进程[%s]没运行, 触发when_no_run注册的动作", options['grep'])
                # await self.run_steps_async(steps) # 不要await，否则monitor_pid()要async，而执行yaml文件中的run_steps()是不支持调用async动作的
                pool.exec(self.run_steps_async, steps) # 耗时操作扔到线程池执行
                # pool.exec(self.run_steps_async, steps, get_vars(True))

        # 3 使用递归+延迟来实现定时检查
        interval = options.get('interval', 10)
        self.loop.call_later(interval, self.monitor_pid, options)

    def grep_pid(self, grep):
        '''
        监控进程，如果进程不存在，则抛异常
        :param grep: 用 `ps aux | grep` 搜索进程时要搜索的关键字，支持多个，用|分割
        :return:
        '''
        if self._pid_grep is not None and self._pid_grep != grep:
            raise Exception(f"框架只支持监控一个进程：已监控[{self._pid_grep}]进程")
        self._pid_grep = grep
        pid = get_pid_by_grep(grep)
        if pid is None:
            raise Exception(f"不存在匹配[{grep}]的进程")
        if "\n" in pid:
            raise Exception(f"关键字[{grep}]匹配了多个进程: " + pid.replace('\n', ','))
        log.info(f"关键字[%s]匹配进程: %s", grep, pid)
        # 记录进程id+进程
        self._pid = pid
        self._proc = ProcInfo(pid)

    # -------------------------------- 监控jvm(进程+gc日志+线程日志)的动作 -----------------------------------
    def monitor_gc_log(self, steps, file):
        '''
        监控gc日志文件内容追加，要解析gc日志
          变量 gc 记录当前行解析出来的gc信息
          变量 gc_log 记录gc日志文件
        :param steps: 每次定时要执行的步骤
        :param file: gc日志文件路径
        :return:
        '''
        if self.gc_parser is not None:
            raise Exception('只支持解析单个gc log')
        self.gc_parser = GcLogParser(file)
        self.gc_parser.parse() # 先解析整个gc log，但不触发报警，只是为了记录历史gc
        async def read_line(line):
            # 解析gc信息
            gc = self.gc_parser.parse_gc_line(line)
            if gc != None:
                # 将gc信息塞到变量中，以便子步骤能读取
                vars = {'gc': gc}
                # 执行子步骤
                await self.run_steps_async(steps, vars)
        self.do_tail(file, read_line)

    def get_current_gc(self, is_full):
        '''
        获得当前gc信息
        :param is_full: 是否full gc
        :return:
        '''
        # 获得当前gc
        gc = get_var('gc')
        if gc is None:
            raise Exception('当前子动作没有定义在 monitor_gc_log 动作内')

        # 匹配gc类型
        if gc['is_full'] == is_full:
            return gc

        return None

    # -------------------------------- dump -----------------------------------
    async def dump_jvm_heap(self, filename_pref):
        '''
        导出监控的进程的jvm堆快照
        :param filename_pref: 文件名前缀
        :return:
        '''
        try:
            self.check_moniter_java('导出jvm堆快照')
            # 如果有告警就用告警条件作为文件名前缀
            filename_pref = self.fix_alert_filename_pref(filename_pref, "JvmHeap")
            now = ts.now2str("%Y%m%d%H%M%S")
            file = f'{filename_pref}-{now}.hprof'
            cmd = f"jmap -dump:live,format=b,file='{file}' {self.pid}"
            await run_command_async(cmd)
            # os.rename(file1, file2)
            log.info(f"导出jvm堆快照: %s", file)
            return file
        except Exception as ex:
            log.error("MonitorBoot.dump_jvm_heap()异常: " + str(ex), exc_info=ex)

    async def dump_jvm_thread(self, filename_pref):
        '''
        导出监控的进程的jvm线程栈
        :param filename_pref: 文件名前缀
        :return:
        '''
        try:
            self.check_moniter_java('导出jvm线程栈')
            # 如果有告警就用告警条件作为文件名前缀
            filename_pref = self.fix_alert_filename_pref(filename_pref, "JvmThread")
            now = ts.now2str("%Y%m%d%H%M%S")
            file = f'{filename_pref}-{now}.tdump'
            cmd = f"jstack -l {self.pid} > '{file}'"
            await run_command_async(cmd)
            log.info(f"导出jvm线程栈: %s", file)
            return file
        except Exception as ex:
            log.error("MonitorBoot.dump_jvm_thread()异常: " + str(ex), exc_info=ex)

    async def dump_jvm_gcs_xlsx(self, config):
        '''
        将jvm gc信息导出到xlsx
        :param config 配置，包含 {filename_pref, bins, interval}
        :return:
        '''
        try:
            if self.gc_parser is None:
                raise Exception("没用使用动作 monitor_gc_log 来监控与解析gc日志")

            if config is None:
                config = {}
            filename_pref = config.get('filename_pref')
            bins = config.get('bins')
            interval = config.get('interval')

            # 如果有告警就用告警条件作为文件名前缀
            filename_pref = self.fix_alert_filename_pref(filename_pref, "JvmGC")
            file = self.gc_parser.gcs2xlsx(filename_pref, bins, interval)
            log.info(f"导出jvm gc信息: %s", file)
            return file
        except Exception as ex:
            log.error("MonitorBoot.dump_jvm_gcs_xlsx()异常: " + str(ex), exc_info=ex)

    # 将所有进程信息导出到xlsx
    async def dump_all_proc_xlsx(self, filename_pref):
        try:
            proc = None
            if self._pid is not None:
                proc = {
                    'PID': self._pid,
                    'Command': self.pname,
                }
            # 如果有告警就用告警条件作为文件名前缀
            filename_pref = self.fix_alert_filename_pref(filename_pref, "ProcStat")
            file = await all_proc_stat2xlsx(filename_pref, proc)
            log.info(f"导出所有进程信息: %s", file)
            return file
        except Exception as ex:
            log.error("MonitorBoot.dump_all_proc_xlsx()异常: " + str(ex), exc_info=ex)

    # 如果有告警就用告警条件作为文件名前缀
    def fix_alert_filename_pref(self, filename_pref, default):
        if filename_pref is None:
            # 如果有告警放到告警目录下
            alert_dir = get_var('alert_dir', False)
            if alert_dir is not None:
                filename_pref = f"{alert_dir}/{default}"

        return filename_pref or default

    # 将系统信息导出到csv
    async def dump_sys_csv(self, filename_pref):
        try:
            if filename_pref is None:
                filename_pref = 'Sys'
            now = ts.now2str()
            today, time = now.split(' ')
            # 建文件
            file = f'{filename_pref}-{today}.csv'
            if not os.path.exists(file):
                cols = ['date', 'time', 'cpu%/s', 'mem%/s', 'mem_used(MB)', 'disk_read(MB/s)', 'disk_write(MB/s)', 'net_sent(MB/s)', 'net_recv(MB/s)']
                self.append_csv_row(file, cols)

            # 导出一行系统信息
            sys = await SysInfo().presleep_all_fields()
            row = [today, time, sys.cpu_percent, sys.mem_percent, sys.mem_used, sys.disk_read, sys.disk_write, sys.net_sent, sys.net_recv]
            # 转可读的文件大小
            for i in range(3, len(row)):
                row[i] = bytes2file_size(row[i], 'M', False)
            self.append_csv_row(file, row)
            return file
        except Exception as ex:
            log.error("MonitorBoot.dump_sys_csv()异常: " + str(ex), exc_info=ex)

    # 将监控的进程信息导出到csv
    async def dump_1proc_csv(self, filename_pref):
        try:
            if filename_pref is None:
                filename_pref = 'Proc'
            now = ts.now2str()
            today, time = now.split(' ')
            # 建文件
            file = f'{filename_pref}-{self.pname}[{self.pid}]-{today}.csv'
            if not os.path.exists(file):
                cols = ['date', 'time', 'cpu%/s', 'mem_used(MB)', 'mem%', 'status']
                self.append_csv_row(file, cols)

            # 导出一行进程信息
            proc = await ProcInfo(self.pid).presleep_all_fields()
            row = [today, time, proc.cpu_percent, bytes2file_size(proc.mem_used, 'M', False), proc.mem_percent, proc.status]
            self.append_csv_row(file, row)
        except Exception as ex:
            log.error("MonitorBoot.dump_1proc_csv()异常: " + str(ex), exc_info=ex)

    def append_csv_row(self, file, vals):
        # 修正小数
        self.fix_float(vals)
        # 文件加一行
        with open(file, 'a+', encoding='utf-8', newline='') as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow(vals)

    # 修正小数
    def fix_float(self, vals):
        for i in range(0, len(vals)):
            v = vals[i]
            if isinstance(v, float):
                vals[i] = '%.4f' % v

    def compare_gc_logs(self, config):
        '''
        对比多个gc log，并将对比结果存到excel中
        :param config: {logs, interval, filename_pref}，其中
                        logs: gc log，必填
                        interval: 分区的时间间隔，单位秒，必填
                        filename_pref: 生成的结果excel文件前缀
        :return:
        '''
        logs = config['logs']
        interval = config.get('interval') or 30
        interval = int(interval)
        filename_pref = config.get('filename_pref')
        file = GcLogParser.compare_gclogs2xlsx(logs, interval, filename_pref)
        log.info(f"对比gc log并将结果存到excel: %s", file)

    # 在指定秒数后结束
    def stop_after(self, run_seconds):
        # 按秒数定时: 代码少，但思路绕，虽然他定义是循环定时执行，因为第一次执行时loop已经结束，因此他只能执行一次
        self.scheduler.add_job(self.loop.stop, 'interval', seconds=int(run_seconds)+3) # 多加3秒是多给点时间来执行`到点但未执行的任务`

    # 在指定时间结束
    # :param stop_time 结束时间，如2022-7-6 13:44:10
    def stop_at(self, stop_time):
        self.scheduler.add_job(self.loop.stop, 'date', run_date=stop_time)

# cli入口
def main():
    # 基于yaml的执行器
    boot = MonitorBoot()
    # 读元数据：author/version/description
    dir = os.path.dirname(__file__)
    meta = read_init_file_meta(dir + os.sep + '__init__.py')
    # 步骤配置的yaml
    step_files, option = parse_cmd('MonitorBoot', meta['version'])
    if len(step_files) == 0:
        raise Exception("Miss step config file or directory")
    try:
        # 指定运行时间(秒)
        if option.runtime is not None:
            boot.stop_after(option.runtime)

        # 执行yaml配置的步骤
        boot.run(step_files)
    except Exception as ex:
        log.error(f"Exception occurs: current step file is %s", boot.step_file, exc_info = ex)
        raise ex

if __name__ == '__main__':
    main()