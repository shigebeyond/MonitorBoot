[GitHub](https://github.com/shigebeyond/MonitorBoot) | [Gitee](https://gitee.com/shigebeyond/MonitorBoot)

# MonitorBoot - yaml驱动linux系统监控

## 概述
框架通过编写简单的yaml, 就可以执行一系列复杂的性能监控步骤, 如告警/dump jvm堆快照/dump jvm线程栈/提取变量/打印变量等，极大的简化了伙伴编写监控脚本的工作量与工作难度，大幅提高人效；

框架通过提供类似python`for`/`if`/`break`语义的步骤动作，赋予伙伴极大的开发能力与灵活性，能适用于广泛的监控场景。

框架提供`include`机制，用来加载并执行其他的步骤yaml，一方面是功能解耦，方便分工，一方面是功能复用，提高效率与质量，从而推进监控脚本整体的工程化。

## 特性
3. 支持通过yaml来配置执行的步骤，简化了监控脚本开发:
每个步骤可以有多个动作，但单个步骤中动作名不能相同（yaml语法要求）;
动作代表一种监控操作，如schedule/alert/send_email/dump_sys_csv等等;
7. 支持类似python`for`/`if`/`break`语义的步骤动作，灵活适应各种场景
8. 支持`include`引用其他的yaml配置文件，以便解耦与复用

## 同类yaml驱动测试框架
[HttpBoot](https://github.com/shigebeyond/HttpBoot)
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

## 步骤配置文件及demo
用于指定多个步骤, 示例见源码 [example](https://github.com/shigebeyond/MonitorBoot/tree/main/example) 目录下的文件;

顶级的元素是步骤;

每个步骤里有多个动作(如schedule/alert/send_email/dump_sys_csv)，如果动作有重名，就另外新开一个步骤写动作，这是由yaml语法限制导致的，但不影响步骤执行。

简单贴出2个demo

## 配置详解
支持通过yaml来配置执行的步骤;

每个步骤可以有多个动作，但单个步骤中动作名不能相同（yaml语法要求）;

动作代表一种监控操作，如schedule/alert/send_email/dump_sys_csv等等;

下面详细介绍每个动作:


2. sleep: 线程睡眠; 
```yaml
sleep: 2 # 线程睡眠2秒
```

3. print: 打印, 支持输出变量/函数; 
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

54. exec: 执行命令, 可用于执行 HttpBoot/MonitorBoot/AppiumBoot/MiniumBoot 等命令，以便打通多端的用例流程
```yaml
exec: ls
exec: MonitorBoot test.yml
```
