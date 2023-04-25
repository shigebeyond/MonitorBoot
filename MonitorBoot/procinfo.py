import asyncio
import json
import time
import psutil
from pyutilb.cmd import get_pid_by_grep
from pyutilb.lazy import lazyproperty
from pyutilb.log import log
from MonitorBoot.sysinfo import PresleepMixin

# 进程信息，如cpu/内存/磁盘等
class ProcInfo(PresleepMixin):

    # 要睡1s的字段
    sleep_fields = 'cpu_percent|dio'.split('|')

    def __init__(self, pid):
        self.pid = pid
        self.proc = psutil.Process(int(pid))
        if self.proc.status() not in (psutil.STATUS_RUNNING, psutil.STATUS_SLEEPING):
            log.error(f"进程[{pid}]没运行")
            self.proc = None

        self.last_dio = None  # 记录上一秒磁盘io统计(读写字节数)，以便通过下一秒的值的对比来计算读写速率

    # 预备：部分指标需要隔1秒调2次，以便通过通过下一秒的值的对比来计算指标值
    def presleep_field(self, expr):
        if 'cpu_percent' in expr:
            # 1 对 self.proc.cpu_percent(interval)，当interval不为空，则阻塞
            # self.proc.cpu_percent(1) # 会阻塞1s
            # 2 当interval为空时，计算的cpu时间是相对上一次调用的，第1次计算直接返回0，因此主动在前一秒调用一下，让后续动作的调用有结果
            self.proc.cpu_percent()  # 对 self.proc.cpu_percent(1) 的异步实现
            return True

        if 'dio' in expr:
            self.last_dio = self.proc.io_counters()
            return True

        return False

    # 是否java进程
    def is_java(self):
        return self.proc.name == "java" \
               or self.proc.exe.endswith("java")

    # 进程名
    @property
    def name(self):
        ret = self.proc.name
        if ret == "java":
            for p in self.proc.cmdline[1:]:
                if not p.startswith('-'): # 忽略选项，返回主类
                    return p
        return ret

    # 进程状态
    @property
    def status(self):
        return self.proc.status()

    # 已用内存
    @property
    def mem_used(self):
        return self.proc.memory_full_info().uss

    # 内存使用率
    @property
    def mem_percent(self):
        return self.proc.memory_percent()

    # cpu的使用频率
    @property
    def cpu_percent(self):
        return self.proc.cpu_percent(1)

    # 磁盘io计数(读写字节数)
    @lazyproperty
    def dio(self):
        return self.proc.io_counters()

    # 读速率 = 当前读字节数 - 上一秒读字节数
    @property
    def disk_read(self):
        return self.dio.read_bytes - self.last_dio.read_bytes

    # 写速率 = 当前写字节数 - 上一秒写字节数
    @property
    def disk_write(self):
        return self.dio.write_bytes - self.last_dio.write_bytes

if __name__ == '__main__':
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
    print("p.memory_full_info(): " + str(p.memory_full_info()))
    print("p.memory_percent(): " + str(p.memory_percent()))
    print("p.open_files(): " + str(p.open_files()))
    print("p.connections(): " + str(p.connections()))
    print("p.is_running(): " + str(p.is_running()))
    print("p.io_counters(): " + str(p.io_counters()))
    print(json.dumps(p.as_dict()))
