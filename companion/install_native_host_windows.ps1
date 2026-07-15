param(
  [Parameter(Mandatory = $true)]
  [string]$ExtensionId
)

$ErrorActionPreference = "Stop"

$HostName = "com.localtube.dub.engine"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HostPath = Join-Path $ScriptDir "native_host.py"
$ManifestPath = Join-Path $ScriptDir "$HostName.json"
$RegistrySubkey = "Software\Google\Chrome\NativeMessagingHosts\$HostName"

$Manifest = @{
  name = $HostName
  description = "LocalTube Dub local AI engine"
  path = $HostPath
  type = "stdio"
  allowed_origins = @("chrome-extension://$ExtensionId/")
}

$Manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $ManifestPath -Encoding UTF8
$RegistryKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($RegistrySubkey)
$RegistryKey.SetValue("", $ManifestPath, [Microsoft.Win32.RegistryValueKind]::String)
$RegistryKey.Close()

Write-Host "Installed LocalTube Dub Native Messaging host for extension: $ExtensionId"
Write-Host "Restart Chrome if the extension was already open."
