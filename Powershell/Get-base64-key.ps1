# File names
$source = $args[0]
$dest = "$($source).b64.txt"

# Get the content of the file and convert to bytes
$key = (Get-Content $source -Raw)
$bytes = [System.Text.Encoding]::UTF8.GetBytes($key)

# Convert bytes to base 64 string and write out to file
$out = [System.Convert]::ToBase64String($bytes)
$out | Set-Content -Path $dest
