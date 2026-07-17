param(
    [string]$ConfigPath = "config/sample_config.toml"
)

Write-Host "IAM Automation environment validation"
Write-Host "User: $env:USERDOMAIN\$env:USERNAME"
Write-Host "Computer: $env:COMPUTERNAME"
Write-Host "Python:"
python --version
python scripts/validate_environment.py --config $ConfigPath
