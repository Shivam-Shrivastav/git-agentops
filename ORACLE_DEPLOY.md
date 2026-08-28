# Free hosting on Oracle Cloud Always Free (ARM, 4 vCPU / 24 GB)

This gets you a **free, always-free** Linux VPS that runs the exact
`docker-compose.prod.yml` from `DEPLOY.md` — no re-architecture, no card
charge as long as you stay in the free shapes.

> Read this alongside `DEPLOY.md` — once the VM is up and Docker is
> installed, you follow `DEPLOY.md` for the actual stack deploy.

The target: **1× VM.Standard.A1.Flex, 4 OCPU, 24 GB RAM, Ubuntu 22.04
(aarch64).** This is part of Oracle's Always Free tier (up to 4 OCPU +
24 GB ARM total, 200 GB block storage).

---

## A. Sign up for Oracle Cloud (Always Free)

1. Go to **https://www.oracle.com/cloud/free/** → **Start for free**.
2. Create an account: email, password, a **credit card for verification**
   (it is **not charged** as long as you stay within Always Free limits),
   and your name/address.
3. **Choose a Home Region carefully — it cannot be changed later.**
   The free ARM shapes are capacity-limited, so pick a **less-crowded**
   region to improve your odds of getting a VM:
   - In India: **ap-hyderabad-1** (newer, usually better capacity than
     ap-mumbai-1).
   - Otherwise: **ap-melbourne-1**, **me-dubai-1**, **eu-milan-1**,
     **eu-stockholm-1** tend to have capacity more often than
     us-ashburn-1 / us-phoenix-1.
4. Finish signup and wait for the provisioning email (can take a few
   minutes to a couple of hours). Then sign in at **cloud.oracle.com**.

> Tip: choose the **"Free Tier"** account type (not Pay As You Go) to
> avoid any accidental charges. The ARM Ampere A1 shape is Always Free
> eligible on the Free Tier account.

---

## B. Create the ARM instance

1. Top-left hamburger → **Compute → Instances → Create instance**.
2. **Image**: click *Change image* → pick **Canonical Ubuntu 22.04**
   (the aarch64 build — it appears automatically once the ARM shape is
   selected). *Change image* → *Canonical Ubuntu 22.04* → *Select*.
3. **Shape**: click *Change shape* → **Ampere** →
   **VM.Standard.A1.Flex** → set **Number of OCPUs = 4** and
   **Amount of memory (GB) = 24** → *Select shape*.
4. **Networking**: keep the default (it creates a new VCN + public
   subnet). Ensure **"Assign a public IPv4 address"** is selected.
5. **Add SSH keys**: choose **"Generate a key pair"** →
   **Download BOTH** the private key (`*.key`) and public key (`*.pub`).
   **You cannot SSH in without the private key — save it somewhere safe.**
   (Or use your own existing public key.)
6. **Create**.

If it spins for a bit and then says **"Out of host capacity"** — see
section C. If it succeeds, note the **Public IP Address** shown on the
instance page.

---

## C. If you get "Out of host capacity"

This is common — the free ARM pool is often full in popular regions.
Options, easiest first:

1. **Retry a few times over a day or two** at off-peak hours (early
   morning in that region). Capacity frees up as others' trials expire.
2. **Try a different region**: your Always Free resources can live in
   any region your tenancy subscribes to. Hamburger → **Regions** (top
   bar) → switch → repeat section B there.
3. **Automation**: a small loop hitting the OCI API to retry every ~2
   minutes grabs capacity the moment it appears. (I can give you a
   script for this if you want.)

Don't shrink to a smaller shape to "just get something" — 1 GB boxes
can't run this stack.

---

## D. Open ports 80 and 443 (TWO firewalls)

Oracle blocks inbound traffic at **both** the cloud network layer **and**
the OS firewall. You must open 80/443 in each.

### D1. Cloud: VCN security list
1. Hamburger → **Networking → Virtual cloud networks** → click your VCN
   → **Security Lists** → the default security list.
2. **Add Ingress Rules** (add two):
   - Source `0.0.0.0/0`, IP Protocol TCP, Destination Port **80**.
   - Source `0.0.0.0/0`, IP Protocol TCP, Destination Port **443**.
   (Source CIDR `0.0.0.0/0` = anywhere; tighten later if you like.)
   Egress is already `0.0.0.0/0` by default — leave it.

### D2. OS: iptables on the VM
SSH in first (see section E), then:
```bash
sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```
(The `6` inserts these before Oracle's default REJECT rule at position 6.)

---

## E. SSH in and install Docker

From your laptop (the private key from B5):
```bash
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<PUBLIC-IP>
```
Default user is **`ubuntu`**. Then on the VM:
```bash
sudo apt-get update
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
# apply the group: log out and back in, or:
newgrp docker
docker --version          # sanity check
```
On ARM this installs the aarch64 Docker — all our images have ARM64
manifests, so `docker compose up --build` works natively.

### Open the OS firewall (section D2) now if you haven't.
```bash
sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

---

## F. Reserve a permanent public IP + point a domain at it

### F1. Reserve the IP (so it doesn't change if the VM restarts)
1. Hamburger → **Networking → IP Management → Reserved Public IPs**
   → **Reserve Public IP Address** (name it, e.g. `agentops`).
2. Note the reserved IP. (To attach it to your instance: Instances →
   your instance → **Attached VNICs** → primary VNIC → **IPv4 Addresses**
   → edit → switch from Ephemeral to *No Public IP*, then re-edit →
   *Reserved Public IP* → pick the one you reserved.)

### F2. Point a domain/subdomain at it (needed for Caddy HTTPS)
Caddy needs a hostname that resolves to the VM to get a Let's Encrypt
certificate. Free options if you don't own a domain:
- **DuckDNS** (https://www.duckdns.org): log in, create a subdomain like
  `yourname.duckdns.org`, point it at the reserved public IP. Let's
  Encrypt issues certs for `*.duckdns.org` — works with Caddy.
- **nip.io** (`<ip>.nip.io`) works for testing but is rate-limited; prefer
  DuckDNS.

Set `DOMAIN=yourname.duckdns.org` in `.env`.

---

## G. Deploy the stack

Now follow **`DEPLOY.md`** on the VM:

```bash
git clone <your-repo-url> agentops-prototype
cd agentops-prototype
cp .env.prod.example .env
# edit .env: DOMAIN, AUTH_USER, GITHUB_TOKEN, OPENROUTER_API_KEY
```

Generate the bcrypt hash **with `$$` escaping** (see DEPLOY.md step 3):
```bash
HASH=$(docker compose -f docker-compose.prod.yml run --rm caddy \
  caddy hash-password --plaintext 'YOUR_PASSWORD')
python3 -c "print('AUTH_HASH=' + __import__('sys').argv[1].replace('\$','\$\$'))" "$HASH" >> .env
```

Build and start:
```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f caddy   # watch cert issuance
```

Then open **`https://yourname.duckdns.org`** (browser prompts for
`AUTH_USER` / your password) and trigger a run:
```bash
curl -u <AUTH_USER>:<PASSWORD> -X POST https://yourname.duckdns.org/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"task":"list open issues in Shivam-Shrivastav/Data-Structures"}'
```

---

## H. Keep it free / don't get reclaimed

- Oracle reclaims Always Free instances that are **idle for a week+**.
  Normal agent/dashboard traffic keeps it active; if unused for a while,
  SSH in occasionally or schedule a tiny cron ping.
- Stay within Always Free shapes (4 OCPU / 24 GB ARM total, 200 GB
  block storage). Don't enable paid services.
- Check usage anytime: Hamburger → **Billing & Cost Management**.

## I. ARM-specific note

This is `aarch64`, not x86. The local test in `DEPLOY.md` was x86, but
every base image we use ships an ARM64 manifest
(`postgres:16-alpine`, `redis:7-alpine`, `caddy:2-alpine`,
`python:3.12-slim`, `node:20-slim`), and the Python deps
(langchain/langgraph/pydantic/uvicorn/requests) have ARM64 wheels — so
`docker compose up --build` builds natively on ARM. If any package
falls back to compiling from source, `sudo apt-get install -y build-essential`
covers it.