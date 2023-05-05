[GitHub](https://github.com/shigebeyond/MonitorBoot) | [Gitee](https://gitee.com/shigebeyond/MonitorBoot)

# MonitorBoot - yaml驱动linux系统监控

## 概述
框架通过编写简单的yaml, 就可以执行一系列复杂的系统或进程性能监控处理, 如告警/dump jvm堆快照/dump jvm线程栈/提取变量/打印变量等，极大的简化了伙伴编写监控脚本的工作量与工作难度，大幅提高人效；

框架通过提供类似python`for`/`if`/`break`语义的步骤动作，赋予伙伴极大的开发能力与灵活性，能适用于广泛的监控场景。

框架提供`include`机制，用来加载并执行其他的步骤yaml，一方面是功能解耦，方便分工，一方面是功能复用，提高效率与质量，从而推进监控脚本整体的工程化。

底层实现使用协程，高性能

## 特性
1. 支持通过yaml来配置执行的步骤，简化了监控脚本开发:
每个步骤可以有多个动作，但单个步骤中动作名不能相同（yaml语法要求）;
动作代表一种监控操作，如schedule/alert/send_email/dump_sys_csv等等;
2. 支持类似python`for`/`if`/`break`语义的步骤动作，灵活适应各种场景;
3. 支持用`include`动作引用其他的yaml配置文件，以便解耦与复用;
4. 支持用`schedule`动作来实现定时处理;
5. 支持用`monitor_gc_log`动作来订阅与解析gc log，以便分析与监控gc耗时或频率;
6. 支持3类指标的告警: 1 系统性能指标 2 进程性能指标 3 gc耗时或频率指标
7. 支持导出多种性能报告文件，如jvm堆快照/jvm线程栈/gc记录的xlsx/所有进程信息的xlsx/有时序的系统性能指标的csv/有时序的进程性能指标的csv
8. 定时处理与异步执行命令都是使用协程来实现，高性能。

## 同类yaml驱动的框架
[HttpBoot](https://github.com/shigebeyond/HttpBoot)
[SeleniumBoot](https://github.com/shigebeyond/SeleniumBoot)
[AppiumBoot](https://github.com/shigebeyond/AppiumBoot)
[MiniumBoot](https://github.com/shigebeyond/MiniumBoot)
[ExcelBoot](https://github.com/shigebeyond/ExcelBoot)

## todo
1. 支持更多的动作

## 安装
```
pip3 install MonitorBoot
```

安装后会生成命令`MonitorBoot`;

注： 对于深度deepin-linux系统，生成的命令放在目录`~/.local/bin`，建议将该目录添加到环境变量`PATH`中，如
```
export PATH="$PATH:/home/shi/.local/bin"
```

## 使用
```
# 1 执行单个文件
MonitorBoot 步骤配置文件.yml

# 2 执行多个文件
MonitorBoot 步骤配置文件1.yml 步骤配置文件2.yml ...

# 3 执行单个目录, 即执行该目录下所有的yml文件
MonitorBoot 步骤配置目录

# 4 执行单个目录下的指定模式的文件
MonitorBoot 步骤配置目录/step-*.yml
```

如执行 `MonitorBoot example/step-mn52.yml`，输出如下
```
......
```

## 步骤配置文件
用于指定多个步骤, 示例见源码 [example](https://github.com/shigebeyond/MonitorBoot/tree/main/example) 目录下的文件;

顶级的元素是步骤;

每个步骤里有多个动作(如schedule/alert/send_email/dump_sys_csv)，如果动作有重名，就另外新开一个步骤写动作，这是由yaml语法限制导致的，但不影响步骤执行。

## 配置详解
支持通过yaml来配置执行的步骤;

每个步骤可以有多个动作，但单个步骤中动作名不能相同（yaml语法要求）;

动作代表一种监控操作，如schedule/alert/send_email/dump_sys_csv等等;

下面详细介绍每个动作:

1. sleep: 线程睡眠; 
```yaml
sleep: 2 # 线程睡眠2秒
```

2. print: 打印, 支持输出变量/函数; 
```yaml
# 调试打印
print: "总申请数=${dyn_data.total_apply}, 剩余份数=${dyn_data.quantity_remain}"
```

变量格式:
```
$msg 一级变量, 以$为前缀
${data.msg} 多级变量, 用 ${ 与 } 包含
```

函数格式:
```
${random_str(6)} 支持调用函数，目前仅支持以下几个函数: random_str/random_int/random_element/incr
```

函数罗列:
```
random_str(n): 随机字符串，参数n是字符个数
random_int(n): 随机数字，参数n是数字个数
random_element(var): 从list中随机挑选一个元素，参数var是list类型的变量名
incr(key): 自增值，从1开始，参数key表示不同的自增值，不同key会独立自增
```

3. config_email: 配置邮件信息
```yaml
- config_email:
      host: smtp.qq.com
      password: $emailpass
      from_name: MonitorBoot
      from_email: aaa@qq.com
      to_name: shigebeyond # 可选，
      to_email: bbb@qq.com
```

4. send_email: 发送邮件
```yaml
- send_email:
    title: hello
    msg: hello world
```

5. schedule: 定时处理，就是每隔指定秒数就执行下子步骤
```yaml
# 定时处理
- schedule(5): # 每隔5秒 
    # 执行子步骤
    - print: '每隔5s触发: ${now()}'
```

6. tail: 订阅文件中最新增加的行，其中变量 tail_line 记录最新增加的行
```yaml
- tail(/home/shi/test.log): # 订阅文件 /home/shi/test.log   
    # 执行子步骤，能读到变量 tail_line
    - print: '最新行: $tail_line'
```

7. alert: 告警处理
```yaml
- alert: # 告警
    # 告警条件
    # 1 系统的性能指标相关的条件
    - sys.cpu_percent >= 90 # cpu使用率 >= 90%
    - sys.mem_used >= 1024M # 已使用内存 >= 1024M
    - sys.mem_free <= 1024M # 剩余内存 <= 1024M
    - sys.disk_percent >= 90 # 磁盘使用率 >= 90%
    - sys.disk_read >= 10M # 读速率 >= 10M
    - sys.disk_write >= 10M # 写速率 >= 10M
    - sys.net_recv >= 10M # 接收速率 >= 10M
    - sys.net_sent >= 10M # 发送速率 >= 10M

    # 2 监控的进程的性能指标相关的条件，仅在有监控进程的情况下使用
    - proc.cpu_percent >=90 # cpu的使用频率 >= 90%
    - proc.mem_used >= 1024M # 已用内存 >= 1024M
    - proc.mem_percent >= 1024M # 内存使用率 >= 1024M
    - proc.disk_read >= 10M # 读速率 >= 10M
    - proc.disk_write >= 10M # 写速率 >= 10M
  
    # 3 gc指标相关的条件，仅在有监控gc log的情况下使用
    - ygc.costtime > 5 # minor gc耗时 > 5s
    - fgc.costtime > 5
    - fgc.interval < 10 # full gc间隔时间 < 10s
```

8. when_alert: 记录当发生告警要调用的动作
```yaml
- when_alert: # 发生告警时要执行以下子步骤
    # 子步骤
    - send_alert_email: # 发告警邮件
```

9. send_alert_email: 发告警邮件
```yaml
- send_alert_email: # 发告警邮件
```

10. monitor_pid: 监控进程的pid，其实现就是定时调用 grep_pid 动作
```yaml
# 监控进程的pid
- monitor_pid:
    grep: java | visualvm | org.netbeans.Main # 用 `ps aux | grep` 搜索进程时要搜索的关键字，支持多个，用|分割
    interval: 10 # 定时检查的时间间隔，可省，默认10秒
    when_no_run: # 没运行时执行以下步骤
      - exec: nohup jvisualvm & # 重启程序
```

11. grep_pid: 搜索进程的pid
```yaml
grep_pid: java | visualvm | org.netbeans.Main # 用 `ps aux | grep` 搜索进程时要搜索的关键字，支持多个，用|分割
```

12. monitor_gc_log: 监控gc日志
```yaml
# 监控gc日志
- monitor_gc_log(/home/shi/code/testing/kt-test/gc.log):
    # 当有新的gc记录时，执行以下子步骤
    - when_alert: # 发生告警时要执行以下步骤
        - send_alert_email: # 发告警邮件
    - alert: # 告警
          - ygc.costtime > 5 # gc耗时 > 5s
          - fgc.costtime > 5
          - fgc.interval < 10 # gc间隔时间 < 10s
```

13. dump_jvm_heap: 导出jvm堆快照
```yaml
- dump_jvm_heap: # dump jvm堆快照(如果你监控了jvm进程)
```

14. dump_jvm_thread: 导出jvm线程栈
```yaml
- dump_jvm_thread: # dump jvm线程栈(如果你监控了jvm进程)
```

15. dump_jvm_gcs_xlsx: 导出gc记录的xlsx
```yaml
- dump_jvm_gcs_xlsx: # dump gc记录
```

16. dump_all_proc_xlsx: 导出所有进程信息的xlsx
```yaml
- dump_all_proc_xlsx: # dump所有进程
```

17. dump_sys_csv: 将系统性能指标导出到csv中，性能指标有：cpu%/s, mem%/s, mem_used(MB), disk_read(MB/s), disk_write(MB/s), net_sent(MB/s), net_recv(MB/s)；一般配合`schedule`动作来使用
```yaml
- dump_sys_csv:
- dump_sys_csv: 导出的csv文件前缀
```

18. dump_1proc_csv: 将当前被监控的进程的性能指标导出到csv中，性能指标有：cpu%/s, mem_used(MB), mem%, status；一般配合`schedule`动作来使用
```yaml
- dump_1proc_csv:
- dump_1proc_csv: 导出的csv文件前缀
```

19. exec: 执行命令
```yaml
exec: ls
```

## 案例介绍
### 1 监控系统性能
[监控脚本](example/dump_sys.yml)
1. 定时监控系统的性能指标，并将指标值写入到csv中；
2. 性能指标有：cpu%/s, mem%/s, mem_used(MB), disk_read(MB/s), disk_write(MB/s), net_sent(MB/s), net_recv(MB/s)

```
# example/dump_sys.yml

# 配置邮件账号
- config_email:
  host: smtp.qq.com
  password: $emailpass
  from_name: MonitorBoot
  from_email: ???@qq.com
  to_name: ???
  to_email: ???@qq.com

# 定时做系统告警
- schedule(10):
    - when_alert: # 发生告警时要执行以下步骤
        - send_alert_email: # 发告警邮件
        - dump_all_proc_xlsx: # dump所有进程
    - alert: # 告警
      # 告警条件
        - sys.mem_free <= 1024M # 剩余内存 <= 1024M
        - cpu_percent >= 90 # cpu使用率 >= 90%
      # - disk_percent >= 90 # 磁盘使用率 >= 90%
```

[运行视频](https://www.zhihu.com/zvideo/1637876392099291137)

### 2 监控进程性能
[监控脚本](example/dump_process.yml)
1. 定时监控指定进程的性能指标，并将指标值写入到csv中；
2. 性能指标有：cpu%/s, mem_used(MB), mem%, status
```
# example/dump_process.yml

# 监控进程的pid，当进程不存在时重启程序
- monitor_pid:
  grep: java | visualvm | org.netbeans.Main # 用 `ps aux | grep` 搜索进程时要搜索的关键字，支持多个，用|分割
  interval: 5 # 定时检查的时间间隔，可省，默认10秒
  when_no_run: # 没运行时执行以下步骤
  - exec: nohup jvisualvm & # 重启程序

# 定时导出进程信息
- schedule(5):
    - dump_1proc_csv: # dump当前监控的进程
```

[运行视频](https://www.zhihu.com/zvideo/1637878398616952833)

### 3 监控进程存活
[监控脚本](example/monitor_and_restart_process.yml)
1. 定时监控进程的存活状态
2. 如果进程未运行，则重启
```
# example/monitor_and_restart_process.yml

# 监控进程的pid，当进程不存在时重启程序
- monitor_pid:
  grep: java | visualvm | org.netbeans.Main # 用 `ps aux | grep` 搜索进程时要搜索的关键字，支持多个，用|分割
  interval: 10 # 定时检查的时间间隔，可省，默认10秒
  when_no_run: # 没运行时执行以下步骤
  - exec: nohup jvisualvm & # 重启程序
```

[运行视频](https://www.zhihu.com/zvideo/1637875128171290626)

### 4 监控系统并报警
[报警脚本](example/alert_sys.yml)
1. 定时做系统性能指标检查，当满足告警条件时触发告警
2. 告警处理：发告警邮件 + dump所有进程
```
# example/alert_sys.yml

# 配置邮件账号
- config_email:
  host: smtp.qq.com
  password: $emailpass
  from_name: MonitorBoot
  from_email: ???@qq.com
  to_name: ???
  to_email: ???@qq.com

# 定时做系统告警
- schedule(10):
    - when_alert: # 发生告警时要执行以下步骤
        - send_alert_email: # 发告警邮件
        - dump_all_proc_xlsx: # dump所有进程
    - alert: # 告警
      # 告警条件
        - sys.mem_free <= 1024M # 剩余内存 <= 1024M
        - cpu_percent >= 90 # cpu使用率 >= 90%
      # - disk_percent >= 90 # 磁盘使用率 >= 90%
```

[运行视频](https://www.zhihu.com/zvideo/1637880842050281473)

### 5 监控jvm gc log并报警
[报警脚本](example/alert_jvm_gc.yml)
1. 订阅gc log文件变更，解析与检查gc指标，当满足告警条件时触发告警
2. 告警处理：发邮件+dump堆快照+dump线程栈+dump gc记录
```
# example/alert_jvm_gc.yml

# 准备：要先启动 kt-test 项目中的java主类 vm.chapter2.GcTestForMonitorBoot

# 配置邮件账号
- config_email:
  host: smtp.qq.com
  password: $emailpass
  from_name: MonitorBoot
  from_email: ???@qq.com
  to_name: ???
  to_email: ???@qq.com

# 监控进程的pid
- monitor_pid:
  grep: java | GcTestForMonitorBoot

# 监控gc日志
- monitor_gc_log(/home/shi/code/testing/kt-test/gc.log):
    - when_alert: # 发生告警时要执行以下步骤
        - send_alert_email: # 发告警邮件
        - dump_jvm_heap: # dump jvm堆快照(如果你监控了jvm进程)
        - dump_jvm_thread: # dump jvm线程栈(如果你监控了jvm进程)
        - dump_jvm_gcs_xlsx: # dump gc记录
    - alert: # 告警
      - ygc.costtime > 5 # gc耗时 > 5s
      - fgc.costtime > 5
      - fgc.interval < 10 # gc间隔时间 < 10s
```

[运行视频](https://www.zhihu.com/zvideo/1637882765587828736)
