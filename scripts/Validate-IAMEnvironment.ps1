# -----------------------------------------------------------------------------
# File: scripts/Validate-IAMEnvironment.ps1
# Purpose: Provides an operational utility for Validate-IAMEnvironment.
# Responsibilities: Validates prerequisites, prepares runtime paths, and invokes the requested application operation.
# Dependencies: Operating-system shell, Python runtime, and project scripts, as applicable.
# Inputs/outputs: Inputs: command-line arguments and configured paths. Outputs: validation messages, files, or process status.
# Author: Miguel Fernandez.
# Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
# -----------------------------------------------------------------------------

param(
    [string]$ConfigPath = "config/sample_config.toml"
)

Write-Host "IAM Automation environment validation"
Write-Host "User: $env:USERDOMAIN\$env:USERNAME"
Write-Host "Computer: $env:COMPUTERNAME"
Write-Host "Python:"
python --version
python scripts/validate_environment.py --config $ConfigPath
