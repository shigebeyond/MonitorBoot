import asyncio
import time
import psutil
from pyutilb.cmd import get_pid_by_grep

# 系统信息，如cpu/内存/磁盘等
class SysInfo(object):

    # 在执行步骤前，提前做好准备
    @classmethod
    async def prepare_fields_in_steps(cls, steps):
        sys = SysInfo()
        for step in steps:
            if 'alert' in step: # alert动作
                for expr in step['alert']: # alert参数是告警表达式
                    await sys.do_prepare_field(expr)
        return sys

    # 准备所有指标
    @classmethod
    async def prepare_all_fields(cls):
        sys = SysInfo()
        fields = ['cpu_percent', 'dio', 'noi']
        for field in fields:
            await sys.do_prepare_field(field)
        return sys

    def __init__(self):
        self.last_dio = None # 记录上一秒磁盘io统计(读写字节数)，以便通过下一秒的值的对比来计算读写速率
        self.last_nio = None # 记录上一秒网络io统计(读写字节数)，以便通过下一秒的值的对比来计算读写速率

    # 准备：部分指标需要隔1秒调2次，以便通过通过下一秒的值的对比来计算指标值
    async def do_prepare_field(self, expr):
        need_sleep = True
        if 'cpu_percent' in expr:
            # 1 对 psutil.cpu_percent(interval)，当interval不为空，则阻塞
            # psutil.cpu_percent(1) # 会阻塞1s
            # 2 当interval为空时，计算的cpu时间是相对上一次调用的，第1次计算直接返回0，因此主动在前一秒调用一下，让后续动作的调用有结果
            psutil.cpu_percent()  # 对 psutil.cpu_percent(1) 的异步实现
        elif 'dio' in expr:
            self.last_dio = psutil.disk_io_counters()
        elif 'nio' in expr:
            self.last_nio = psutil.net_io_counters()
        else:
            need_sleep = False
        # 睡1s
        if need_sleep:
            await asyncio.sleep(1)

    # 告警已使用内存
    @property
    def mem_used(self):
        memory_info = psutil.virtual_memory()
        return memory_info.used

    # 告警可用内存
    @property
    def mem_free(self):
        # free 是真正尚未被使用的物理内存数量。
        # available 是应用程序认为可用内存数量，available = free + buffer + cache
        memory_info = psutil.virtual_memory()
        return memory_info.free

    # 告警cpu使用率
    @property
    def cpu_percent(self):
        return psutil.cpu_percent()

    # 告警磁盘使用率
    @property
    def disk_percent(self):
        disk_info = psutil.disk_usage("/")  # 根目录磁盘信息
        return float(disk_info.used / disk_info.total * 100)  # 根目录使用情况

    # 磁盘io
    def disk_io(self):
        dio = psutil.disk_io_counters()
        # 读写速率 = 当前读写字节数 - 上一秒读写字节数
        self.disk_read = dio.read_bytes - self.last_dio.read_bytes
        self.disk_write = dio.write_bytes - self.last_dio.write_bytes

    # 网络io
    def network_io(self):
        nio = psutil.net_io_counters()
        # 读写速率 = 当前读写字节数 - 上一秒读写字节数
        self.net_recv = nio.bytes_recv - self.last_dio.bytes_recv
        self.net_sent = nio.bytes_sent - self.last_dio.bytes_sent


if __name__ == '__main__':
    print("psutil.cpu_percent(): " + str(psutil.cpu_percent(None, percpu=True)))
    print("psutil.disk_io_counters(): " + str(psutil.disk_io_counters(perdisk=True)))
    pid = get_pid_by_grep("java | com.intellij.idea.Main")
    p = psutil.Process(int(pid))
    print("p.cmdline(): " + str(p.cmdline()))
    print("p.name(): " + str(p.name()))
    # cpu_percent() 要不带参数，要不调用2次，中间sleep至少1秒，否则 cpu_percent()返回的值不准确
    print("p.cpu_percent(): " + str(p.cpu_percent()))
    time.sleep(0.8)
    print("p.cpu_percent(): " + str(p.cpu_percent()))
    print("p.cpu_num(): " + str(p.cpu_num()))
    print("p.memory_info(): " + str(p.memory_info()))
    print("p.memory_percent(): " + str(p.memory_percent()))
    print("p.open_files(): " + str(p.open_files()))
    print("p.connections(): " + str(p.connections()))
    print("p.is_running(): " + str(p.is_running()))
