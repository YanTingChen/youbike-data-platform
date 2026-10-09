[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)]
    [string]$SshKey,
    # 部署目標的 inventory 檔（相對於 deploy/ansible）。明確宣告成參數並給別名 -i：
    # 否則 PowerShell 會把 -i 當成自己的內建參數而報錯
    [Alias("i")]
    [string]$Inventory = "inventory.yml",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AnsibleArgs
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

docker build --quiet --tag youbike-ansible "$root\deploy\ansible" | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 私鑰先複製到容器內並收緊權限：從 Windows 掛載的檔案權限是所有人可讀，ssh 會拒絕使用
docker run --rm `
    --volume "${root}:/workspace" `
    --volume "${SshKey}:/keys/deploy_key:ro" `
    youbike-ansible `
    sh -c 'install -m 600 /keys/deploy_key /tmp/deploy_key && exec ansible-playbook playbook.yml "$@"' -- -i $Inventory @AnsibleArgs

exit $LASTEXITCODE
