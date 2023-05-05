from pyutilb import ts
from pyutilb.cmd import get_ip
from pyutilb.file import *
from pyutilb.log import log
from pyutilb.util import get_var

# 告警异常
class AlertException(Exception):
    def __init__(self, condition, msg):
        super(AlertException, self).__init__(msg)
        self.condition = condition # 告警条件

# 告警条件的检查者
class AlertExaminer(object):
    # 告警字段
    alert_cols = [
        'sys.mem_free',
        'sys.cpu_percent',
        'sys.disk_percent',
        'ygc.costtime',
        'ygc.interval',
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
            col, op, param = re.split(r'\s+', condition.strip(), 3)
            # 获得col所在的对象
            if '.' not in col:
                col = 'sys.' + col
            obj_name, col2 = col.split('.', 1)
            obj = self.get_op_object(obj_name)
            if obj is None:
                return
            # 读col值
            val = self.get_col_val(obj, col2)
            # 执行操作符函数
            ret = bool(self.run_op(op, val, param))
        except Exception as ex:
            log.error("执行告警条件[" + condition + "]错误: " + str(ex), exc_info=ex)
            return

        if ret:
            msg = f"主机[{get_ip()}]在{ts.now2str()}时发生告警: {col}({val}) {op} {param}"
            raise AlertException(condition, msg)

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
            raise Exception(f'Invalid validate operator: {op}')
        # 调用校验函数
        # log.debug(f"Call operator: {op}={param}")
        op = self.ops[op]
        return op(val, param)

