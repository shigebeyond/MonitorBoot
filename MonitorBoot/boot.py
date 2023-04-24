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
            'monitor_jpid': self.monitor_jpid,
            'grep_jpid': self.grep_jpid,
            'dump_heap': self.dump_heap,
            'dump_thread': self.dump_thread,
            'monitor_gc_log': self.monitor_gc_log,
            'sys2csv': self.sys2csv,
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

    # 执行完的后置处理
    def on_end(self):
        # 死循环处理s
        asyncio.get_event_loop().run_forever()

    # -------------------------------- 普通动作 -----------------------------------
    # 配置邮件服务器
    def config_email(self, config):
        emailer.config_email(config)

    # 发送邮件
    def send_email(self, params):
        emailer.send_email(params['title'], params['msg'])

    # 异步执行步骤：主要是优化 psutil.cpu_percent(1) 的阻塞带来的性能问题，要扔到eventloop所在的线程中运行
    async def run_steps_async(self, steps):
        # 提前准备好SysInfo
        sys = await SysInfo.prepare_fields_in_steps(steps)
        set_var('sys', sys)

        # 真正执行步骤
        name = threading.current_thread()  # MainThread
        print(f"thread[{name}]执行步骤")
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
            set_var('tail_line', line)
            # 执行子步骤
            await self.run_steps_async(steps)
            # 清理变量
            set_var('tail_line', None)
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

    # 告警处理
    def alert(self, exprs):
        if not isinstance(exprs, (str, list)):
            raise Exception("告警参数必须str或list类型")
        if isinstance(exprs, str):
            exprs = [exprs]

        try:
            # 1 逐个表达式来执行告警
            for expr in exprs:
                self.do_alert(expr)
        except Exception as ex:
            log.error(str(ex), exc_info = ex)
            set_var('alert_msg', str(ex))
            # 2 当发生告警异常要调用when_alert注册的动作
            steps = get_var('when_alert')
            if steps:
                log.info("告警发生, 触发when_alert注册的动作")
                self.run_steps(steps)
            # 清空alert相关变量
            set_var('when_alert', None)
            set_var('alert_msg', None)

    def do_alert(self, expr):
        '''
        处理单个字段的告警，如果符合条件，则抛出报警异常
        :param expr: 告警的条件表达式，只支持简单的三元表达式，操作符只支持 =, <, >, <=, >=
               如 mem_free <= 1024M
        '''
        # 分割字段+操作符+值
        col, op, param = re.split(r'\s+', expr.strip(), 3)
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
        if 'ygc' == obj_name:
            return self.check_current_gc(False)
        if 'fgc'  == obj_name:
            return self.check_current_gc(True)
        return get_var('sys')

    def run_op(self, op, val, param):
        '''
        执行操作符：就是调用函数
        :param op: 操作符
        :param val: 校验的值
        :param param: 参数
        :return:
        '''
        if op not in self.ops:
            raise Exception(f'Invalid validate operator: {op}')
        # 调用校验函数
        log.debug(f"Call validate operator: {op}={param}")
        op = self.ops[op]
        return op(val, param)

    # 发送告警邮件
    def send_alert_email(self):
        msg = get_var('alert_msg')
        if ':' in msg:
            title = substr_before(msg, ':')
        else:
            title = msg
        self.send_email({
            'title': title,
            'msg': msg,
        })

    # -------------------------------- 监控java进程 -----------------------------------
    # 监控的java进程id
    @property
    def jpid(self):
        pid = get_var('jpid')
        if pid is None:
            raise Exception("无jpid")
        return pid

    def monitor_jpid(self, options):
        '''
        监控java进程，如果进程不存在，则抛异常
        :param options 选项，包含
                    grep: 用ps aux搜索进程时要搜索的关键字
                    interval: 定时检查的时间间隔，用于定时检查进程是否还存在，为null则不检查
                    when_no_run: 当进程没运行时执行的步骤
        :return:
        '''
        # 1 使用 ps aux | grep 来获得pid
        try:
            self.grep_jpid(options['grep'])
        except Exception as ex:
            # 2 当进程没运行时执行的步骤
            if 'when_no_run' in options and options['when_no_run'] is not None:
                log.info(f"进程[{options['grep']}]没运行, 触发when_no_run注册的动作")
                self.run_steps(options['when_no_run'])

        # 3 使用递归+延迟来实现定时检查
        interval = self.get_interval(options)
        self.loop.call_later(interval, self.monitor_jpid, options)

    # 从选项中获得时间间隔
    def get_interval(self, options):
        if 'interval' in options and options['interval'] is not None:
            return int(options['interval'])
        return 10

    def grep_jpid(self, grep):
        '''
        监控java进程，如果进程不存在，则抛异常
        :param grep: 用ps aux搜索进程时要搜索的关键字，支持多个，用|分割
        :return:
        '''
        pid = get_pid_by_grep(grep)
        if pid is None:
            raise Exception(f"不存在匹配的java进程: {grep}")
        set_var('jpid', pid)

    @pool.run_in_pool
    async def dump_heap(self, filename_pref):
        '''
        生成堆快照
        :param filename_pref: 文件名前缀
        :return:
        '''
        try:
            now = ts.now2str().replace(' ', '_')
            file = f'{filename_pref}-{now}.hprof'
            cmd = f'jmap -dump:live,format=b,file={file} {self.jpid}'
            await run_command_async(cmd)
            log.info(f"生成堆快照文件: {file}")
        except Exception as ex:
            log.error("MonitorBoot.dump_heap()异常: " + str(ex), exc_info=ex)

    @pool.run_in_pool
    async def dump_thread(self, filename_pref):
        '''
        生成线程栈
        :param filename_pref: 文件名前缀
        :return:
        '''
        try:
            now = ts.now2str().replace(' ', '-')
            file = f'{filename_pref}-{now}.stack'
            cmd = f'jstack -l {self.jpid} > {file}'
            await run_command_async(cmd)
            log.info(f"生成线程栈文件: {file}")
        except Exception as ex:
            log.error("MonitorBoot.dump_thread()异常: " + str(ex), exc_info=ex)

    # -------------------------------- 线程处理 -----------------------------------
    # 挑出繁忙的线程： 用 pidstat -t -p pid
    def pick_busy_thread(self):
        # 1 获得线程
        df = self.get_threads_df()
        # 2 按cpu降序
        df = df.sort_values(by='%CPU', ascending=False)
        # 3 选择第一个
        # 取前2个: print(df.head(2))
        # 取第1个: df.iloc[0]
        row = df.iloc[0]
        log.info(f"进程[{self.jpid}]中最繁忙的线程为: {row}")

    # 挑出等待很久的线程
    def pick_wait_thread(self):
        pass

    # 通过 pidstat -t -p pid 来获得线程
    def get_threads_df(self):
        # 1 执行命令
        output = run_command_async(f'pidstat -t -p {self.jpid}')
        '''
            输出如下，要干掉前两行
            Linux 5.10.60-amd64-desktop (shi-PC) 	2023年04月23日 	_x86_64_	(6 CPU)
    
            11时28分27秒   UID      TGID       TID    %usr %system  %guest   %wait    %CPU   CPU  Command
            11时28分27秒  1000      9702         -   19.37    0.50    0.00    0.00   19.87     0  java
            11时28分27秒  1000         -      9702    0.00    0.00    0.00    0.00    0.00     0  |__java
            '''
        output = re.sub(r"^.+\n\n", '', output)
        # 2 将命令结果转为df
        df = cmd_output2dataframe(output)
        # 3 过滤业务线程: 通过构建 VM_THREAD 列来过滤
        df['VM_THREAD'] = self.build_vm_thread_col(df)
        df2 = df.loc[lambda x: x['VM_THREAD'] == False]
        del df2['VM_THREAD']
        return df2

    # 构建是否vm线程，非业务线程
    def build_vm_thread_col(self, df):
        ret = []
        for i, row in df.iterrows():
            # 第一条是进程而不是线程，如java且tid为-，不要
            # 其他: vm线程不要
            val = row['TID'] == '-' \
                  or self.is_vm_thread(row['Command'])
            ret.append(val)
        return ret

    # 是否vm线程，非业务线程
    features = 'GC Thread#,G1 Main Marker,G1 Conc#,G1 Refine#,G1 Young RemSet,VM Thread,Reference Handl,Finalizer,Signal Dispatch,Service Thread,C2 CompilerThre,C1 CompilerThre,Sweeper thread,VM Periodic Tas,Common-Cleaner,process reaper,GC Thread#,GC Thread#,GC Thread#,GC Thread#,GC Thread#,G1 Refine#,G1 Conc#,G1 Refine#,G1 Refine#'.split(',')
    def is_vm_thread(self, thread_name):
        for f in self.features:
            if f in thread_name:
                return True
        return False

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
                set_var('gc', gc)
                # 执行子步骤
                await self.run_steps_async(steps)
                # 清理变量
                set_var('gc', None)
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

    # -------------------------------- 输出到csv -----------------------------------
    # 将系统信息存到csv中
    @pool.run_in_pool
    async def sys2csv(self, _):
        try:
            now = ts.now2str()
            today, time = now.split(' ')
            file = f'MointorBoot{today}.csv'
            if not os.path.exists(file):
                cols = ['date', 'time', 'cpu%/s', 'mem_used(MB)', 'disk_read(MB/s)', 'disk_write(MB/s)', 'net_sent(MB/s)', 'net_recv(MB/s)']
                self.append_csv_row(file, cols)

            sys = await SysInfo.prepare_all_fields()
            row = [today, time, sys.cpu_percent, sys.mem_used, sys.disk_read, sys.disk_write, sys.net_sent, sys.net_recv]
            self.append_csv_row(file, row)
        except Exception as ex:
            log.error("MonitorBoot.sys2csv()异常: " + str(ex), exc_info=ex)

    def append_csv_row(self, file, line):
        with open(file, 'a+', encoding='utf-8', newline='') as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow(line)

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
    # output = run_command(f'pidstat -t -p 9702')
    '''
    输出如下，要干掉前两行
    Linux 5.10.60-amd64-desktop (shi-PC) 	2023年04月23日 	_x86_64_	(6 CPU)

    11时28分27秒   UID      TGID       TID    %usr %system  %guest   %wait    %CPU   CPU  Command
    11时28分27秒  1000      9702         -   19.37    0.50    0.00    0.00   19.87     0  java
    11时28分27秒  1000         -      9702    0.00    0.00    0.00    0.00    0.00     0  |__java
    '''
    '''
    # re.search(r"^[\n]+\n\n", output)
    output = re.sub(r"^.+\n\n", '', output)
    print(output)
    df = cmd_output2dataframe(output)
    print(df)
    # 导出线程名
    # print(df['Command'])
    # df[['Command']].to_csv('cmd.csv')
    # 过滤业务线程
    print('------过滤业务线程')
    df['VM_THREAD'] = MonitorBoot().build_vm_thread_col(df)
    # df.to_csv('d1.csv')
    #df2 = df.loc[df['VM_THREAD']] # 过滤vm线程 -- []内部参数为bool值的series，可用于过滤行
    df2 = df.loc[lambda x: x['VM_THREAD'] == False] # 过滤业务线程
    # df2.to_csv('d2.csv')
    print(df2)
    print('------按cpu降序')
    df3 = df2.sort_values(by='%CPU', ascending=False)
    print(df3)
    print(df3.head(2))
    print(df3.iloc[0])
    '''