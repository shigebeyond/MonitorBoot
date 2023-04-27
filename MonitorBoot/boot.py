#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os
import time
import psutil
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyutilb.strs import substr_after, substr_before
from pyutilb.tail import Tail
from pyutilb.util import *
from pyutilb.file import *
from pyutilb.cmd import *
from pyutilb import YamlBoot, EventLoopThreadPool, ts
from pyutilb.log import log
from MonitorBoot import emailer
from MonitorBoot.gc_log_parser import GcLogParser
from MonitorBoot.procinfo import ProcInfo
from MonitorBoot.procstat import dump_all_proc_stat
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
            'when_alert': self.when_alert,
            'alert': self.alert,
            'send_alert_email': self.send_alert_email,
            'monitor_pid': self.monitor_pid,
            'grep_pid': self.grep_pid,
            'monitor_gc_log': self.monitor_gc_log,
            'dump_jvm_heap': self.dump_jvm_heap,
            'dump_jvm_thread': self.dump_jvm_thread,
            'dump_sys_csv': self.dump_sys_csv,
            'dump_1proc_csv': self.dump_1proc_csv,
            'dump_all_proc_xlsx': self.dump_all_proc_xlsx,
        }
        self.add_actions(actions)

        # 当前ip
        self.ip = get_ip()

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
        self._proc = None

        # ----- 告警处理 -----
        # 告警字段
        self.alert_cols = [
            'mem_free',
            'cpu_percent',
            'disk_percent',
            'ygc.costtime',
            'ygc.interval',
            'fgc.costtime',
            'fgc.interval',
        ]
        # 操作符函数映射
        self.ops = {
            '=': lambda val, param: float(val) == float(param),
            '>': lambda val, param: float(val) > float(param),
            '<': lambda val, param: float(val) < float(param),
            '>=': lambda val, param: float(val) >= float(param),
            '<=': lambda val, param: float(val) <= float(param),
        }
        # 记录告警条件的过期时间, key是告警条件(表示类型), value是过期时间，没过期就不处理告警，用来限制同条件的告警的处理频率，如限制导出进程xlsx或发邮件
        self.alert_condition_expires = {}

    # 执行完的后置处理
    def on_end(self):
        # 死循环处理s
        asyncio.get_event_loop().run_forever()

    # -------------------------------- 普通动作 -----------------------------------
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
            log.info(f"----- 调试模式下模拟发邮件: title = {title}, msg = {msg} -----")
            return
        emailer.send_email(title, msg)

    # 异步执行步骤：主要是优化 psutil.cpu_percent(1) 的阻塞带来的性能问题，要扔到eventloop所在的线程中运行
    async def run_steps_async(self, steps, vars = {}):
        # 提前预备好SysInfo
        sys = await SysInfo().presleep_fields_in_steps(steps)
        vars['sys'] = sys

        # 应用变量，因为变量是在ThreadLocal中，只能在同步代码中应用
        with UseVars(vars):
            # 真正执行步骤
            # name = threading.current_thread()  # MainThread
            # print(f"thread[{name}]执行步骤")
            self.run_steps(steps)

    def schedule(self, steps, wait_seconds):
        '''
        定时器
        :param steps: 每次定时要执行的步骤
        :param wait_seconds: 时间间隔,单位秒
        :return:
        '''
        self.scheduler.add_job(self.run_steps_async, 'interval', args=(steps,), seconds=int(wait_seconds))

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

    def alert(self, conditions, expire_sec = 600):
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
                self.do_alert(condition)
        except Exception as ex:
            # 2 处理告警异常：异常=告警发生
            self.handle_alert_exception(condition, ex, int(expire_sec))

    def handle_alert_exception(self, condition, ex, expire_sec):
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
        if not self.check_alert_expired(condition, expire_sec):
            if condition in self.alert_condition_expires:
                print("过期时间为: "+ ts.timestamp2str(self.alert_condition_expires[condition]))
            log.info(f"在{expire_sec}秒内忽略同条件[{condition}]的告警")
            return

        # 处理告警异常
        set_var('alert_msg', msg)
        set_var('alert_condition', condition)
        # 当发生告警异常要调用when_alert注册的动作
        steps = get_var('when_alert')
        if steps:
            log.info("告警发生, 触发when_alert注册的动作")
            self.run_steps(steps)
        # 清空alert相关变量
        set_var('when_alert', None)
        set_var('alert_msg', None)
        set_var('alert_condition', None)

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

    def do_alert(self, condition):
        '''
        处理单个字段的告警，如果符合条件，则抛出报警异常
        :param condition: 告警的条件表达式，只支持简单的三元表达式，操作符只支持 =, <, >, <=, >=
               如 mem_free <= 1024M
        '''
        # 分割字段+操作符+值
        col, op, param = re.split(r'\s+', condition.strip(), 3)
        # 获得col所在的对象
        if '.' not in col:
            col = 'sys.' + col
        obj_name, col2 = col.split('.')
        obj = self.get_op_object(obj_name)
        # 读col值
        val = getattr(obj, col2)
        # 执行操作符函数
        ret = bool(self.run_op(op, val, param))
        if ret:
            msg = f"主机[{self.ip}]在{ts.now2str()}时发生告警: {col}({val}) {op} {param}"
            raise Exception(msg)

    def get_op_object(self, obj_name):
        if 'sys' == obj_name:
            return get_var('sys')
        if 'proc' == obj_name:
            return get_var('proc')
        if 'ygc' == obj_name:
            return self.check_current_gc(False)
        if 'fgc' == obj_name:
            return self.check_current_gc(True)
        raise Exception(f"Invalid object name: {obj_name}")

    def run_op(self, op, val, param):
        '''
        执行操作符：就是调用函数
        :param op: 操作符
        :param val: 校验的值
        :param param: 参数
        :return:
        '''
        # 处理参数: 文件大小字符串换算为字节数
        if param[-1] in file_size_units:
           param = file_size2bytes(param)
        # 校验操作符
        if op not in self.ops:
            raise Exception(f'Invalid validate operator: {op}')
        # 调用校验函数
        # log.debug(f"Call operator: {op}={param}")
        op = self.ops[op]
        return op(val, param)

    # 发送告警邮件
    def send_alert_email(self, _):
        # 发邮件
        msg = get_var('alert_msg')
        if ':' in msg:
            title = substr_before(msg, ': ')
        else:
            title = msg
        self.do_send_email(title, msg)

    # -------------------------------- 监控进程 -----------------------------------
    # 监控的进程id
    @property
    def pid(self):
        if self._pid is None:
            raise Exception("无pid")
        return self._pid

    # 检查是否监控java进程
    def check_moniter_java(self, action):
        if self._pid is None:
            raise Exception("无pid")
        if not self._proc.is_java:
            pname = f"{self._proc.name}[{self.pid}]"
            raise Exception(f"非java进程: {pname}, 不能执行{action}")

    def monitor_pid(self, options):
        '''
        监控进程，如果进程不存在，则抛异常
        :param options 选项，包含
                    grep: 用ps aux搜索进程时要搜索的关键字
                    interval: 定时检查的时间间隔，用于定时检查进程是否还存在，为null则不检查
                    when_no_run: 当进程没运行时执行的步骤
        :return:
        '''
        # 1 使用 ps aux | grep 来获得pid
        try:
            self.grep_pid(options['grep'])
        except Exception as ex:
            # 2 当进程没运行时执行的步骤
            if 'when_no_run' in options and options['when_no_run'] is not None:
                log.info(f"进程[{options['grep']}]没运行, 触发when_no_run注册的动作")
                self.run_steps(options['when_no_run'])

        # 3 使用递归+延迟来实现定时检查
        interval = self.get_interval(options)
        self.loop.call_later(interval, self.monitor_pid, options)

    # 从选项中获得时间间隔
    def get_interval(self, options):
        if 'interval' in options and options['interval'] is not None:
            return int(options['interval'])
        return 10

    def grep_pid(self, grep):
        '''
        监控进程，如果进程不存在，则抛异常
        :param grep: 用ps aux搜索进程时要搜索的关键字，支持多个，用|分割
        :return:
        '''
        pid = get_pid_by_grep(grep)
        if pid is None:
            raise Exception(f"不存在匹配[{grep}]的进程")
        if "\n" in pid:
            raise Exception(f"关键字[{grep}]匹配了多个进程: " + pid.replace('\n', ','))
        log.info(f"关键字[{grep}]匹配进程: {pid}")
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
        async def read_line(line):
            # 解析gc信息
            gc = self.gc_parser.parse_gc_line(line)
            if gc != None:
                # 将gc信息塞到变量中，以便子步骤能读取
                vars = {'gc': gc}
                # 执行子步骤
                await self.run_steps_async(steps, vars)
        self.do_tail(file, read_line)

    def check_current_gc(self, is_full):
        '''
        检查当前gc信息
        :param is_full: 是否full gc
        :return:
        '''
        # 获得当前gc
        gc = get_var('gc')
        if gc is None:
            raise Exception('当前子动作没有定义在 monitor_gc_log 动作内')

        # 匹配gc类型
        if gc['is_full'] != is_full:
            return None

        return gc

    # -------------------------------- dump -----------------------------------
    @pool.run_in_pool
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
            cmd = f'jmap -dump:live,format=b,file={file} {self.pid}'
            await run_command_async(cmd)
            log.info(f"导出jvm堆快照: {file}")
            return file
        except Exception as ex:
            log.error("MonitorBoot.dump_jvm_heap()异常: " + str(ex), exc_info=ex)

    @pool.run_in_pool
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
            cmd = f'jstack -l {self.pid} > {file}'
            await run_command_async(cmd)
            log.info(f"导出jvm线程栈: {file}")
            return file
        except Exception as ex:
            log.error("MonitorBoot.dump_jvm_thread()异常: " + str(ex), exc_info=ex)

    # 如果有告警就用告警条件作为文件名前缀
    def fix_alert_filename_pref(self, filename_pref, default):
        if filename_pref is None:
            # 如果有告警就用告警条件作为文件名前缀
            condition = get_var('alert_condition')
            if condition is not None:
                condition = condition.replace(' ', '')
                filename_pref = f"{default}OnAlert[{condition}]"

        return filename_pref or default

    # 将系统信息导出到csv
    @pool.run_in_pool
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
    @pool.run_in_pool
    async def dump_1proc_csv(self, filename_pref):
        try:
            if filename_pref is None:
                filename_pref = 'Proc'
            now = ts.now2str()
            today, time = now.split(' ')
            # 建文件
            file = f'{filename_pref}-{self._proc.name}[{self.pid}]-{today}.csv'
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

    # 将所有进程信息导出到xlsx
    @pool.run_in_pool
    async def dump_all_proc_xlsx(self, filename_pref):
        try:
            proc = {
                'PID': self._pid,
                'Command': self._proc.name,
            }
            file = await dump_all_proc_stat(filename_pref, proc)
            log.info(f"导出所有进程信息: {file}")
            return file
        except Exception as ex:
            log.error("MonitorBoot.dump_all_proc_xlsx()异常: " + str(ex), exc_info=ex)

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
        # 执行yaml配置的步骤
        boot.run(step_files)
    except Exception as ex:
        log.error(f"Exception occurs: current step file is {boot.step_file}", exc_info = ex)
        raise ex

if __name__ == '__main__':
    main()