# Deploying Airlock to a Vultr VM

Two options — both take about 5 minutes.

## Option A — Vultr console + cloud-init (fully automated)

1. Vultr console → **+ Deploy Server** → Cloud Compute → Shared CPU →
   Ubuntu 24.04 x64. A 1 vCPU / 2 GB plan (`vc2-1-2`) works for the demo;
   4 GB is more comfortable when the sandbox runs pandas.
2. Under **Server Settings → Cloud-Init User Data**, paste the contents of
   `deploy/cloud-init.yml` (edit the git URL first).
3. Deploy. After boot (~2 min) Airlock is on `http://<vm-ip>/`.
   Check progress: `ssh root@<ip> tail -f /var/log/cloud-init-output.log`.

## Option B — SSH + setup script

```bash
ssh root@<vm-ip>
apt-get update && apt-get install -y git
git clone https://github.com/YodHeVauHe/airlock.git /srv/airlock
bash /srv/airlock/deploy/setup-vm.sh
```

## After either: plug in the real model

```bash
cd /srv/airlock
nano .env     # set:
              #   AIRLOCK_INFERENCE_API_KEY=vlt-...   (Vultr Serverless Inference)
              #   AIRLOCK_INFERENCE_MODEL=<a model id from /v1/models>
              #   AIRLOCK_MOCK_LLM=0
docker compose -f deploy/docker-compose.yml up -d
```

Model list: `curl https://api.vultrinference.com/v1/models -H "Authorization: Bearer $KEY"`

## Verifying the deployment

- `curl http://<vm-ip>/api/health` → should report `"driver": {..., "docker_ok": true}`
  and `"llm": "vultr-serverless-inference"`.
- Open `http://<vm-ip>/torture` and detonate **rm -rf /** — the containment moment
  for the demo video lives here.
- Submit a real task with `samples/sales.csv` from the repo.

## Enabling the throwaway-instance driver (stretch demo)

In `.env`: `VULTR_API_KEY=<same Vultr key, API access enabled>`,
`AIRLOCK_VULTR_DRIVER=1`, then restart. Tasks can now be dispatched onto entire
disposable Vultr VMs (adds ~1–2 min boot per task). Keep it on the Docker lane
for the live demo; run one Vultr-instance task on camera and show the instance
being created and destroyed in the Vultr console — that's the judging bonus.

## Firewall

Only port 80 (and 22) need to be open. Sandboxes get `--network none` regardless;
the control plane never exposes the docker socket.
