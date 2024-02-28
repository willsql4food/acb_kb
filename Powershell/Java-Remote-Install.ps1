Set-Location C:\

if(Test-Path "C:\Software") 
    {Write-Host 'C:\Software already exists'} 
else {
    New-Item -Path C:\Software -ItemType Directory 
}
if(Test-Path "C:\Software\JavaInstall") 
    {Write-Host 'C:\Software\JavaInstall already exists'} 
else {
    New-Item -Path C:\Software\JavaInstall -ItemType Directory 
}

Write-Host 'Downloading Java installer'
Invoke-WebRequest https://javadl.oracle.com/webapps/download/AutoDL?BundleId=249551_4d245f941845490c91360409ecffb3b4 -OutFile C:\Software\jre-8u401-windows-i586.exe

Write-Host 'Installing Java silently'
C:\Software\jre-8u401-windows-i586.exe /s /L C:\Software\JavaInstall\install.log

Write-Host 'Finished.  Log file contents:'
Get-Content -Path C:\Software\JavaInstall\install.log
