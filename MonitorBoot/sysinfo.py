import asyncio
import time
import psutil
from pyutilb.cmd import get_pid_by_grep
from pyutilb.lazy import lazyproperty

# 为了预备指标，需要提前睡1s
class PresleepMixin(object):
    # 预备所有指标
    async def presleep_all_fields(self):
        # 重置预备字段
        self.reset_presleep_field()

        # 检查是否要预备睡1s
        for field in self.sleep_fields:
            need_sleep = self.has_presleep_field(field)
        # 睡1s
        if need_sleep:
            await asyncio.sleep(1)
        return self

    # 在执行步骤前，提前预备指标
    async def presleep_fields_in_steps(self, steps):
        # 重置预备字段
        self.reset_presleep_field()

        # 检查是否要预备睡1s
        need_sleep = False
        for step in steps:
            if 'alert' in step:  # alert动作
                for expr in step['alert']:  # alert参数是表达式
                    need_sleep = need_sleep or self.has_presleep_field(expr)
        # 睡1s
        if need_sleep:
            await asyncio.sleep(1)
        return self

# 系统信息，如cpu/内存/磁盘等
class SysInfo(PresleepMixin):

    # 要睡1s的字段
    sleep_fields = 'cpu_percent|dio|nio'.split('|')

    def __init__(self):
        self.last_dio = None # 记录上一秒磁盘io统计(读写字节数)，以便通过下一秒的值的对比来计算读写速率
        self.last_nio = None # 记录上一秒网络io统计(读写字节数)，以便通过下一秒的值的对比来计算读写速率

    # 重置预备的字段
    def reset_presleep_field(self):
        self.last_dio = None
        self.last_nio = None

    # 预备：部分指标需要隔1秒调2次，以便通过通过下一秒的值的对比来计算指标值
    def has_presleep_field(self, expr):
        if 'cpu_percent' in expr:
            # 1 对 psutil.cpu_percent(interval)，当interval不为空，则阻塞
            # psutil.cpu_percent(1) # 会阻塞1s
            # 2 当interval为空时，计算的cpu时间是相对上一次调用的，第1次计算直接返回0，因此主动在前一秒调用一下，让后续动作的调用有结果
            psutil.cpu_percent()  # 对 psutil.cpu_percent(1) 的异步实现
            return True

        if 'dio' in expr:
            self.last_dio = psutil.disk_io_counters()
            return True

        if 'nio' in expr:
            self.last_nio = psutil.net_io_counters()
            return True

        return False

    # 磁盘io计数(读写字节数)
    @lazyproperty
    def dio(self):
        return psutil.disk_io_counters()

    # 网络io计数(读写字节数)
    @lazyproperty
    def nio(self):
        return psutil.net_io_counters()

    # 读速率 = 当前读字节数 - 上一秒读字节数
    @property
    def disk_read(self):
        return self.dio.read_bytes - self.last_dio.read_bytes

    # 写速率 = 当前写字节数 - 上一秒写字节数
    @property
    def disk_write(self):
        return self.dio.write_bytes - self.last_dio.write_bytes

    # 接收速率 = 当前接收字节数 - 上一秒接收字节数
    @property
    def net_recv(self):
        return self.nio.bytes_recv - self.last_nio.bytes_recv

    # 发送速率 = 当前发送字节数 - 上一秒发送字节数
    @property
    def net_sent(self):
        return self.nio.bytes_sent - self.last_nio.bytes_sent

    # 已使用内存
    @property
    def mem_used(self):
        memory_info = psutil.virtual_memory()
        return memory_info.used

    # 可用内存
    @property
    def mem_free(self):
        # free 是真正尚未被使用的物理内存数量。
        # available 是应用程序认为可用内存数量，available = free + buffer + cache
        memory_info = psutil.virtual_memory()
        return memory_info.free

    # 内存使用率
    @property
    def mem_percent(self):
        memory_info = psutil.virtual_memory()
        return memory_info.percent

    # cpu使用率
    @property
    def cpu_percent(self):
        return psutil.cpu_percent()

    # 磁盘使用率
    @property
    def disk_percent(self):
        disk_info = psutil.disk_usage("/")  # 根目录磁盘信息
        return float(disk_info.used / disk_info.total * 100)  # 根目录使用情况


if __name__ == '__main__':
    print("psutil.psutil.disk_usage(): " + str(psutil.disk_usage("/")))
    print("psutil.cpu_percent(): " + str(psutil.cpu_percent(None, percpu=True)))
    print("psutil.disk_io_counters(): " + str(psutil.disk_io_counters(perdisk=True)))
