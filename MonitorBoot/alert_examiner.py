import asyncio
from MonitorBoot.sysinfo import SysInfo
from pyutilb import ts
from pyutilb.cmd import get_ip
from pyutilb.file import *
from pyutilb.log import log
from pyutilb.util import get_var, set_var

# 告警异常
class AlertException(Exception):
    def __init__(self, condition, msg):
        super(AlertException, self).__init__(msg)
        self.condition = condition # 告警条件

# 告警条件的检查者
class AlertExaminer(object):
    # 告警字段
    alert_cols = [
        # 1 系统的性能指标相关的条件
        'sys.cpu_percent',
        'sys.mem_used',
        'sys.mem_free',
        'sys.mem_percent',
        'sys.disk_percent',
        'sys.disk_read',
        'sys.disk_write',
        'sys.net_recv',
        'sys.net_sent',

        # 2 监控的进程的性能指标相关的条件，仅在有监控进程的情况下使用
        'proc.cpu_percent',
        'proc.mem_used',
        'proc.mem_percent',
        'proc.disk_read',
        'proc.disk_write',

        # 3 gc指标相关的条件，仅在有监控gc log的情况下使用
        'ygc.costtime',
        'fgc.costtime',
        'fgc.interval',
    ]

    # 操作符函数映射
    ops = {
        '=': lambda val, param: float(val) == float(param),
        '>': lambda val, param: float(val) > float(param),
        '<': lambda val, param: float(val) < float(param),
        '>=': lambda val, param: float(val) >= float(param),
        '<=': lambda val, param: float(val) <= float(param),
    }

    def __init__(self, boot):
        self.boot = boot

    def run(self, condition):
        '''
        检查单个告警条件，如果符合条件，则抛出报警异常
        :param condition: 告警的条件表达式，只支持简单的三元表达式，操作符只支持 =, <, >, <=, >=
               如 mem_free <= 1024M
        '''
        try:
            # 分割字段+操作符+值
            col, op, param = self.parse_condition(condition)
            # 获得col所在的对象
            if '.' not in col:
                col = 'sys.' + col
            if col not in self.alert_cols:
                raise Exception('无效告警字段: ' + col)
            obj_name, col2 = col.split('.', 1)
            obj = self.get_op_object(obj_name)
            if obj is None:
                return

            # 读col值
            val = self.get_col_val(obj, col2)
            if obj_name.endswith('gc') and col2 == 'interval' and val == 0: # 第一次gc是interval=0, 是没有意义的, 直接跳过
                return

            # 执行操作符函数
            ret = bool(self.run_op(op, val, param))
        except Exception as ex:
            log.error("执行告警条件[" + condition + "]错误: " + str(ex), exc_info=ex)
            return

        if ret:
            msg = f"主机[{get_ip()}]在{ts.now2str()}时发生告警: {col}({val}) {op} {param}"
            raise AlertException(condition, msg)

    # 解析条件：分割字段+操作符+值
    def parse_condition(self, condition):
        # 1. 空格分割: wrong 有可能无空格
        # return re.split(r'\s+', condition.strip(), 3)

        # 2. 三元素正则匹配
        mat = re.match('([\w\.]+)\s*([><=]+)\s*(\d+\w?)', condition.strip())
        if mat is None:
            raise Exception("无效条件表达式: " + condition)

        return mat.group(1), mat.group(2), mat.group(3)

    # 获得条件的操作对象: sys+proc 是必填，ygc+fgc非必填
    def get_op_object(self, obj_name):
        if 'sys' == obj_name:
            sys = get_var('sys')
            if sys is None: # 必填
                raise Exception('未准备sys变量')
            return sys

        if 'proc' == obj_name:
            if self.boot._proc is None: # 必填
                raise Exception("没用使用动作 monitor_pid/grep_pid 来监控进程")
            return self.boot._proc

        if 'ygc' == obj_name:
            return self.boot.get_current_gc(False)

        if 'fgc' == obj_name:
            return self.boot.get_current_gc(True)
        raise Exception(f"Invalid object name: {obj_name}")

    # 从操作对象中获得指定字段值
    def get_col_val(self, obj, col):
        # dict类型: ygc+fgc
        if isinstance(obj, dict):
            return obj[col]

        # 对象类型: sys+proc
        return getattr(obj, col)

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
            raise Exception(f'无效校验符: {op}')
        # 调用校验函数
        # log.debug(f"Call operator: %s=%s", op, param)
        op = self.ops[op]
        return op(val, param)


async def test():
    sys = await SysInfo().presleep_all_fields()
    set_var('sys', sys)
    boot = None
    e = AlertExaminer(boot)
    e.run(condition)

if __name__ == '__main__':
    condition = ' sys.net_sent >=10M '
    '''
    mat = re.match('([\w\.]+)\s*([><=]+)\s*(\d+\w?)', condition.strip())
    print(mat)
    for i in range(1, 4):
        print(mat.group(i))
    '''
    asyncio.run(test())


