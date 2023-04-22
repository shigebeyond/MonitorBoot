#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os
import time
import psutil
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyutilb.tail import Tail
from pyutilb.util import *
from pyutilb.file import *
from pyutilb.cmd import *
from pyutilb import YamlBoot, EventLoopThreadPool
from pyutilb.log import log
from MonitorBoot import emailer
from MonitorBoot.gc_log_parser import GcLogParser

# 协程线程池
pool = EventLoopThreadPool(1)

# 基于yaml的监控器
class MonitorBoot(YamlBoot):

    def __init__(self):
        super().__init__()
        # 动作映射函数
        actions = {
            'config_email': self.config_email,
            'schedule': self.schedule,
            'tail': self.tail,
            'alert': self.alert,
            'alert_mem_free': self.alert_mem_free,
            'alert_cpu_percent': self.alert_cpu_percent,
            'alert_disk_percent': self.alert_disk_percent,
            'grep_jpid': self.grep_jpid,
            'monitor_gc_log': self.monitor_gc_log,
            'alert_younggc_costtime': self.alert_younggc_costtime,
            'alert_younggc_interval': self.alert_younggc_interval,
            'alert_fullgc_costtime': self.alert_fullgc_costtime,
            'alert_fullgc_interval': self.alert_fullgc_interval,
        }
        self.add_actions(actions)

        # 告警类型映射处理方法
        self.alert_type_mapping = {
            'mem_free': self.alert_mem_free,
            'cpu_percent': self.alert_cpu_percent,
            'disk_percent': self.alert_disk_percent,
            'younggc_costtime': self.alert_younggc_costtime,
            'younggc_interval': self.alert_younggc_interval,
            'fullgc_costtime': self.alert_fullgc_costtime,
            'fullgc_interval': self.alert_fullgc_interval,
        }

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
        # 监控的java进程id
        self.jpid = None

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

    # 异步执行步骤
    # 主要是优化 psutil.cpu_percent(1) 的阻塞带来的性能问题
    async def run_steps_async(self, steps):
        if self.has_cpu_percent_step(steps):
            # 1 对 psutil.cpu_percent(interval)，当interval不为空，则阻塞
            #psutil.cpu_percent(1) # 会阻塞1s

            # 2 当interval为空时，计算的cpu时间是相对上一次调用的，第1次计算直接返回0，因此主动调用一下，让后续动作的调用有结果
            psutil.cpu_percent() # 对 psutil.cpu_percent(1) 的异步实现
            await asyncio.sleep(1)

        # 真正执行步骤
        name = threading.current_thread()  # MainThread
        print(f"thread[{name}]执行步骤")
        self.run_steps(steps)

    # 是否有获得cpu使用率的步骤
    def has_cpu_percent_step(self, steps):
        return 'alert_cpu_percent' in steps \
            or ('alert' in steps and 'cpu_percent' in steps['alert'])

    def schedule(self, steps, wait_seconds = None):
        '''
        定时器
        :param steps: 每次定时要执行的步骤
        :param wait_seconds: 时间间隔,单位秒
        :return:
        '''
        self.scheduler.add_job(self.run_steps_async, 'interval', args=(steps,), seconds=wait_seconds)

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

    # -------------------------------- 系统告警的动作 -----------------------------------
    # 多类型的告警统一调用
    def alert(self, config):
        for type, params in config:
            func = self.alert_type_mapping[type]
            func(params)

    # 处理告警
    def do_alert(self, msg):
        # todo: 发邮件
        print_exception(msg)

    # 告警可用内存
    def alert_mem_free(self, min_mem):
        # free 是真正尚未被使用的物理内存数量。
        # available 是应用程序认为可用内存数量，available = free + buffer + cache
        memory_info = psutil.virtual_memory()
        if memory_info.free < file_size2bytes(min_mem):
            unit = min_mem[-1]
            free_size = bytes2file_size(memory_info.free, unit)
            self.do_alert(f"主机[{self.ip}]的空闲内存不足为{free_size}, 小于告警的最小内存{min_mem}")

    # 告警cpu使用率
    def alert_cpu_percent(self, max_pcpu):
        pcpu = psutil.cpu_percent()
        if pcpu > self.max_cpu:
            self.do_alert(f"主机[{self.ip}]的cpu使用率过高为{pcpu:.2f}%, 大于告警的最大使用率{max_pcpu}")

    # 告警磁盘使用率
    def alert_disk_percent(self, max_pdisk):
        disk_info = psutil.disk_usage("/") # 根目录磁盘信息
        pdisk = float(disk_info.used / disk_info.total * 100) # 根目录使用情况
        if pdisk > max_pdisk:
            self.do_alert(f"主机[{self.ip}]的磁盘根目录使用率过高为{pdisk:.2f}%, 大于告警的最大使用率{max_pdisk}")

    # -------------------------------- 监控java进程 -----------------------------------
    def grep_jpid(self, grep):
        '''
        监控java进程，如果进程不存在，则抛异常
        :param grep: 用ps aux搜索进程时要搜索的关键字，支持多个，用|分割
        :return:
        '''
        pid = get_pid_by_grep(grep)
        if pid is None:
            raise Exception(f"不存在匹配的java进程: {grep}")
        self.jpid = pid

    # 挑出繁忙的线程
    def pick_busy_thread(self):
        # top -Hp pid
        # pidstat -t -p pid
        pass

    # 挑出等待很久的线程
    def pick_wait_thread(self):
        pass


    # 生成堆快照
    @pool.run_in_pool
    async def dump_heap(self, msg):
        file = 'xxx.hprof'
        cmd = f'jmap -dump:live,format=b,file={file} {self.jpid}'
        await run_command_async(cmd)
        log.info(f"由[{msg}]而生成堆快照文件: {file}")

    # 生成线程栈
    @pool.run_in_pool
    async def dump_thread(self, msg):
        file = 'xxx.stack'
        cmd = f'jstack -l {self.jpid} > {file}'
        await run_command_async(cmd)
        log.info(f"由[{msg}]而生成线程栈文件: {file}")

    # -------------------------------- jvm(进程+gc日志+线程日志)告警的动作 -----------------------------------
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

    # 告警young gc单次耗时
    def alert_younggc_costtime(self, max_gc_costtime):
        self.do_alert_gc_costtime(max_gc_costtime, False)

    # 告警young gc间隔时间
    def alert_younggc_interval(self, min_gc_interval):
        self.do_alert_gc_interval(min_gc_interval, False)

    # 告警full gc单次耗时
    def alert_fullgc_costtime(self, max_gc_costtime):
        self.do_alert_gc_costtime(max_gc_costtime, True)

    # 告警full gc间隔时间
    def alert_fullgc_interval(self, min_gc_interval):
        self.do_alert_gc_interval(min_gc_interval, True)

    def do_alert_gc_costtime(self, max_gc_costtime, is_full):
        '''
        告警gc单次耗时
        :param max_gc_costtime:
        :param is_full: 是否full gc
        :return:
        '''
        gc = self.check_current_gc(is_full)
        if gc is None:
            return

        # 比较gc耗时
        costtime = float(gc['Sum']['cost_time'])
        if costtime > max_gc_costtime:
            self.do_alert(f"主机[{self.ip}]进程[{self.jpid}]gc耗时为{costtime:.2f}s, 大于告警的最大耗时{max_gc_costtime}")

    def do_alert_gc_interval(self, min_gc_interval, is_full):
        '''
        告警gc单次耗时
        :param min_gc_interval: 最小间隔时间
        :param is_full: 是否full gc
        :return:
        '''
        gc = self.check_current_gc(is_full)
        if gc is None:
            return

        interval = float(gc['Sum']['interval'])
        if interval < min_gc_interval:
            self.do_alert(f"主机[{self.ip}]进程[{self.jpid}]gc间隔为{interval:.2f}s, 小于告警的最小间隔{min_gc_interval}")


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
        log.error(f"Exception occurs: current step file is {boot.step_file}, current url is {boot.curr_url}", exc_info = ex)
        raise ex

if __name__ == '__main__':
    # main()

    print("psutil.cpu_percent(): " + str(psutil.cpu_percent(None, percpu=True)))
    print("psutil.disk_io_counters(): " + str(psutil.disk_io_counters(perdisk=True)))

    pid = get_pid_by_grep("java | com.intellij.idea.Main")
    p = psutil.Process(int(pid))
    print("p.cmdline(): " + str(p.cmdline()))
    print("p.name(): " + str(p.name()))
    print("p.cpu_percent(): " + str(p.cpu_percent()))
    time.sleep(0.8)
    print("p.cpu_percent(): " + str(p.cpu_percent()))
    print("p.cpu_num(): " + str(p.cpu_num()))
    print("p.memory_info(): " + str(p.memory_info()))
    print("p.memory_percent(): " + str(p.memory_percent()))
    print("p.open_files(): " + str(p.open_files()))
    print("p.connections(): " + str(p.connections()))
    print("p.is_running(): " + str(p.is_running()))

    run_command(f'top -Hp ')