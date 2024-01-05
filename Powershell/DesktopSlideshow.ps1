# Variables
$sharedFolderPath = "\\path\to\shared\folder" # Replace with the path to your shared folder containing the images
$localFolderPath = "$env:USERPROFILE\Pictures\SlideshowImages"

# Create local folder for slideshow images if it doesn't exist
if (-not (Test-Path $localFolderPath)) {
    New-Item -ItemType Directory -Path $localFolderPath
}

# Download images from shared folder to local folder
$sharedImages = Get-ChildItem -Path $sharedFolderPath -File
foreach ($image in $sharedImages) {
    Copy-Item -Path $image.FullName -Destination $localFolderPath -Force
}

# Set the Background slideshow
$BackgroundKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers"
Set-ItemProperty -Path $BackgroundKeyPath -Name BackgroundType -Type DWord -Value 2
Set-ItemProperty -Path $BackgroundKeyPath -Name SlideshowDirectoryPath1 -Type String -Value $localFolderPath

# Set the Lockscreen slideshow
$LockScreenKeyPath = "HKCU:\SOFTWARE\Policies\Microsoft\Windows\Personalization"
Set-ItemProperty -Path $LockScreenKeyPath -Name LockScreenSlideshow -Type DWord -Value 1
Set-ItemProperty -Path $LockScreenKeyPath -Name LockScreenSlideshowDirectory -Type String -Value $localFolderPath

# Refresh the settings
RUNDLL32.EXE USER32.DLL,UpdatePerUserSystemParameters 1, True