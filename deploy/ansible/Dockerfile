# 執行 Ansible 用的映像：Ansible 不能直接在 Windows 上執行，包成容器後任何有 Docker 的電腦都能部署
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client rsync \
 && rm -rf /var/lib/apt/lists/*

# ansible 套件已內含會用到的 community.docker 與 ansible.posix
RUN pip install --no-cache-dir "ansible>=11,<12"

# 專案資料夾從 Windows 掛進來時權限是「所有人可寫」，Ansible 預設會忽略這種資料夾裡的設定檔；明確指定就會採用
ENV ANSIBLE_CONFIG=/workspace/deploy/ansible/ansible.cfg
WORKDIR /workspace/deploy/ansible
