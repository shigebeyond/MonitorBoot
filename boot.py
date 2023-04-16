#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import sys
import fnmatch
import time

import psutil
import requests
from pyutilb.util import *
from pyutilb.file import *
from pyutilb.cmd import *
import curlify
import threading
from pyutilb import YamlBoot, BreakException, ocr_youdao, SchedulerThread
from pyutilb.log import log
import emailer

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
        self.scheduler_thread = SchedulerThread() # 定时线程
        self.jpid = None # java进程id
        # 上一次gc信息
        self.last_gc = {
            'S0C': 0,
            'S1C': 0,
            'S0U': 0,
            'S1U': 0,
            'EC': 0,
            'EU': 0,
            'OC': 0,
            'OU': 0,
            'MC': 0,
            'MU': 0,
            'CCSC': 0,
            'CCSU': 0,
            'YGC':0,
            'YGCT': 0,
            'FGC':0,
            'FGCT': 0,
            'GCT': 0,
            'time': None,
        }

    # 执行完的后置处理
    def on_end(self):
        # 等待定时线程处理完
        if self.scheduler_thread.thread:
            self.scheduler_thread.thread.join()

    # 定时器
    # :param steps 每次定时要执行的步骤
    # :param wait_seconds 时间间隔,单位秒
    def schedule(self, steps, wait_seconds = None):
        self.scheduler_thread.scheduler.add_job(self.run_steps, 'interval', args=(steps,), seconds=wait_seconds)

    # 配置邮件服务器
    def config_email(self, config):
        emailer.config_email(config)

    # 发送邮件
    def send_email(self, params):
        emailer.send_email(params['title'], params['msg'])

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

    # 监控java进程
    def watch_java_pid(self, grep):
        pid = get_pid_by_grep('java', grep)
        if pid is None:
            raise Exception(f"不存在匹配的java进程: {grep}")
        self.jpid = pid

    # 告警yound gc单次耗时
    def alert_youndgc_time(self, max_gc_costtime):
        self.alert_gc_costtime(max_gc_costtime, 'YGC')

    # 告警full gc单次耗时
    def alert_fullgc_time(self, max_gc_costtime):
        self.alert_gc_costtime(max_gc_costtime, 'FGC')

    # 告警full gc间隔
    def alert_fullgc_time(self, max_gc_costtime):
        self.alert_gc_costtime(max_gc_costtime, 'FGC')

        fgc = int(res[14])
        if self.FGC[str(port)] < fgc:  # If the times of FGC increases
            self.FGC[str(port)] = fgc

            if len(self.FGC_time[str(port)]) > 2:   # Calculate FGC frequency
                frequency = self.FGC_time[str(port)][-1] - self.FGC_time[str(port)][-2]
                if frequency < self.frequencyFGC:    # If FGC frequency is too high, send email.
                    msg = f'The Full GC frequency of port {port} is {frequency}, it is too high. Server IP: {self.IP}'
                    logger.warning(msg)
                    if self.isJvmAlert:
                        thread = threading.Thread(target=notification, args=(msg, ))
                        thread.start()


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
    output = os.popen(f'jstat -gc 7061').read()
    df = cmd_output2data_frame(output)
    print(df)
    exit()

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