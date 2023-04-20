#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import psutil
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyutilb.tail import Tail
from pyutilb.util import *
from pyutilb.file import *
from pyutilb.cmd import *
from pyutilb import YamlBoot
from pyutilb.log import log
import emailer
from .gc_log_parser import GcLogParser

# 基于yaml的监控器
class MonitorBoot(YamlBoot):

    def __init__(self):
        super().__init__()
        # 动作映射函数
        actions = {
            'base_url': self.base_url,
        }
        self.add_actions(actions)

        self.ip = get_ip() # 当前ip
        # 创建调度器
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()
        # tail跟踪
        self.tails = {}
        # gc日志解析器
        self.gcparsers = {}

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

    def schedule(self, steps, wait_seconds = None):
        '''
        定时器
        :param steps: 每次定时要执行的步骤
        :param wait_seconds: 时间间隔,单位秒
        :return:
        '''
        self.scheduler.add_job(self.run_steps, 'interval', args=(steps,), seconds=wait_seconds)

    def tail(self, steps, file):
        '''
        监控文件内容追加，常用于订阅日志变更
           变量 tail_line 记录读到的行
        :param steps: 每次定时要执行的步骤
        :param file: 文件路径
        :return:
        '''
        def read_line(line):
            # 将行塞到变量中，以便子步骤能读取
            set_var('tail_line', line)
            # 执行子步骤
            self.run_steps(steps)
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
    # 告警
    def alert(self, msg):
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
            self.alert(f"主机[{self.ip}]的空闲内存不足为{free_size}, 小于告警的最小内存{min_mem}")

    # 告警cpu使用率
    def alert_cpu_percent(self, max_pcpu):
        pcpu = psutil.cpu_percent(interval=0.5) # 0.5刷新频率
        if pcpu > self.max_cpu:
            self.alert(f"主机[{self.ip}]的cpu使用率过高为{pcpu:.2f}%, 大于告警的最大使用率{max_pcpu}")

    # 告警磁盘使用率
    def alert_disk_percent(self, max_pdisk):
        disk_info = psutil.disk_usage("/") # 根目录磁盘信息
        pdisk = float(disk_info.used / disk_info.total * 100) # 根目录使用情况
        if pdisk > max_pdisk:
            self.alert(f"主机[{self.ip}]的磁盘根目录使用率过高为{pdisk:.2f}%, 大于告警的最大使用率{max_pdisk}")

    # -------------------------------- 监控java进程 -----------------------------------
    def jps_grep(self, grep):
        '''
        监控java进程
        :param grep: 用ps aux搜索进程时要搜索的关键字
        :return:
        '''
        pid = get_pid_by_grep('java', grep)
        if pid is None:
            raise Exception(f"不存在匹配的java进程: {grep}")
        set_var('jpid', pid)

    # 获得当前java进程id
    def jpid(self):
        return get_var('jpid')

    def jmap(self):
        cmd = 'jmap -dump:live,format=b,file=headInfo.hprof 进程id'
        run_command()

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
        self.gcparsers[file] = GcLogParser()
        def read_line(line):
            # 解析gc信息
            gc = self.gcparsers[file].parse_gc_line(line)
            if gc != None:
                # 将gc信息塞到变量中，以便子步骤能读取
                set_var('gc', gc)
                set_var('gc_log', file)
                # 执行子步骤
                self.run_steps(steps)
                # 清理变量
                set_var('gc', None)
                set_var('gc_log', None)
        self.do_tail(file, read_line)

    # 执行子动作时获得当前的gc日志解析器
    def current_gcparser(self):
        file = get_var('gc_log')
        if file is None or file not in self.gcparsers:
            raise Exception(f'无监控gc日志: {file}')
        return self.gcparsers[file]

    # 告警yound gc单次耗时
    def alert_youndgc_time(self, max_gc_costtime):
        self.alert_gc_costtime(max_gc_costtime, 'YGC')

    # 告警full gc单次耗时
    def alert_fullgc_time(self, max_gc_costtime):
        self.alert_gc_costtime(max_gc_costtime, 'FGC')


    # 告警full gc间隔
    def alert_fullgc_interval(self, max_gc_interval):
        self.alert_gc_interval(max_gc_interval, 'FGC')

    def alert_gc_costtime(self, max_gc_costtime, type):
        '''
        告警gc单次耗时
        :param max_gc_costtime:
        :param type: gc类型: YGC / FGC
        :return:
        '''
        gc = self.get_gc()
        num_field = type  # 如 YGC / FGC
        time_field = type + 'T'  # 如 YGCT / FGCT
        if self.last_gc[num_field] < gc[num_field]:  # gc次数增加了
            num = gc[num_field] - self.last_gc[num_field]
            seconds = gc[time_field] - self.last_gc[time_field]
            costtime = seconds / num
            if costtime > max_gc_costtime:
                self.alert(f"主机[{self.ip}]进程[{self.jpid}]gc耗时过大为{costtime:.2f}s, 大于告警的最大耗时{max_gc_costtime}")

    def alert_gc_interval(self, max_gc_interval, type):
        '''
        告警gc单次耗时
        :param max_gc_interval:
        :param type: gc类型: YGC / FGC
        :return:
        '''
        gc = self.get_gc()
        num_field = type  # 如 YGC / FGC
        time_field = type + 'T'  # 如 YGCT / FGCT
        if self.last_gc[num_field] < gc[num_field]:  # gc次数增加了
            num = gc[num_field] - self.last_gc[num_field]
            seconds = gc[time_field] - self.last_gc[time_field]
            costtime = seconds / num
            if costtime > max_gc_interval:
                self.alert(f"主机[{self.ip}]进程[{self.jpid}]gc耗时过大为{costtime:.2f}s, 大于告警的最大耗时{max_gc_costtime}")

    # 获得gc信息
    def get_gc(self):
        now = time.time()
        # 1ms内则返回上一个gc统计命令结果
        if self.last_gc is not None \
            and now - self.last_gc['time'] < 0.001:
            return self.last_gc
        # 执行gc统计命令
        df = run_command_return_dataframe('jstat -gc ' + self.jpid)
        gc = dict(df.loc[0])
        gc['time'] = now
        return gc


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
    main()