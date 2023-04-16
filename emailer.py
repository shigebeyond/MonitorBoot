import smtplib
import socket
from email.header import Header
from email.mime.text import MIMEText

# 配置
config = {
    'from_name': '',
    'from_email': '',
    'password': '',
    'host': '',
    # 'to_email': '',
    # 'to_name': '',
}

# 配置邮件
def config_email(config2):
    global config
    config = config2

# 发邮件
def send_email(title, msg, to_email = None, to_name = None):
    # 收件人默认从配置中取
    if to_email is None and to_name is None:
        to_email = config['to_email']
        to_name = config['to_name']
    if to_name is None:
        to_name = to_email

    message = MIMEText(msg, 'plain', 'utf-8')  # Chinese required 'utf-8'
    message['Subject'] = Header(title, 'utf-8')
    message['From'] = Header(config['from_name'])
    message['To'] = Header(to_name, 'utf-8')

    do_send_email(message, to_email)

# 真正的发邮件
def do_send_email(message, to_email):
    try:
        smtp = smtplib.SMTP_SSL(config['host'], 465)  # qq邮箱
    except socket.error:
        smtp = smtplib.SMTP(config['host'], 25)  # 163邮箱
    smtp.login(config['from_email'], config['password'])
    smtp.sendmail(config['from_email'], to_email, message.as_string())
    smtp.quit()


if __name__ == '__main__':
    sendEmail(1)
