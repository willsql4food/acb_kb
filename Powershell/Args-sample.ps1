Write-Output $args.Count

$i = 0
foreach ($a in $args)
{
    Write-Output "$($i): $($a)"
    $i++
}