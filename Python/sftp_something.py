import paramiko

host,user,pwd = '10.247.96.8', 'foundation_dw', 'pJ5P6RGo-Mb3giTsG0TZ'

xp = paramiko.Transport(host, 22)

xp.connect(None, user, pwd)

s = paramiko.SFTPClient.from_transport(xp)

contents = s.listdir('in/StateLogProducts/')

for f in contents:
    print(f)