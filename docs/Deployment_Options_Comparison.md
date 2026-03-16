# NovaReel — Deployment Options Comparison

> **Goal:** Expose NovaReel for hackathon reviewers within $30/month budget  
> **Current State:** Running on Mac Mini locally

---

## Option 1: **ngrok (Free) + Mac Mini**

### Architecture
```
Mac Mini (local) → ngrok tunnel → Public URL
                    ↓
               Reviewers access
```

### Setup
```bash
# Install ngrok
brew install ngrok

# Start tunnel
ngrok http 8000

# Get URL: https://random-words.ngrok.io
```

### Costs
| Item | Cost/Month |
|---|---|
| ngrok (free) | $0 |
| Electricity (Mac Mini) | ~$5-10 |
| **Total** | **$5-10** |

### Pros
- ✅ **Zero setup time** (5 minutes)
- ✅ **No AWS account needed**
- ✅ **Full NovaReel features** (all AI models work)
- ✅ **Under budget by $20-25**
- ✅ **Complete control** of your environment

### Cons
- ❌ **URL changes on restart** (free version)
- ❌ **Depends on your Mac** being online
- ❌ **Home internet reliability**
- ❌ **Single point of failure** (your Mac)

### Best For
- Quick demo/hackathon
- Testing with real users
- Minimal budget

---

## Option 2: **Cloudflare Tunnel (Free) + Mac Mini**

### Architecture
```
Mac Mini (local) → Cloudflare Tunnel → Persistent URL
                    ↓
               Reviewers access
```

### Setup
```bash
# Install cloudflared
brew install cloudflared

# Login to Cloudflare
cloudflared tunnel login

# Start tunnel
cloudflared tunnel --url http://localhost:8000

# Get URL: https://novareel.trycloudflare.com
```

### Costs
| Item | Cost/Month |
|---|---|
| Cloudflare Tunnel | $0 |
| Electricity (Mac Mini) | ~$5-10 |
| **Total** | **$5-10** |

### Pros
- ✅ **Persistent URL** (doesn't change on restart)
- ✅ **Free** (no cost)
- ✅ **HTTPS included**
- ✅ **Better reliability** than ngrok free
- ✅ **Under budget by $20-25**

### Cons
- ❌ **Still depends on your Mac**
- ❌ **Home internet reliability**
- ❌ **Single point of failure**
- ❌ **Requires Cloudflare account**

### Best For
- Hackathon with stable URL
- Longer demo periods
- When you need consistent URL

---

## Option 3: **AWS EC2 (t3.small)**

### Architecture
```
AWS EC2 (t3.small) → Public IP → Reviewers
       ↓
  NovaReel containers
```

### Setup
```bash
# Launch EC2 instance
- Region: us-east-1
- Instance: t3.small (2 vCPU, 2 GB RAM)
- AMI: Ubuntu 22.04
- Storage: 20 GB SSD

# Install Docker & deploy
ssh ec2-user@<public-ip>
# Run your Docker containers
```

### Costs
| Service | Cost/Month |
|---|---|
| EC2 t3.small | $20 |
| S3 (5 GB) | $0 (free tier) |
| DynamoDB | $0 (free tier) |
| Data transfer | ~$5 (100 GB) |
| **Total** | **~$25** |

### Pros
- ✅ **Professional deployment**
- ✅ **99.9% uptime** (AWS reliability)
- ✅ **Scalable** (can upgrade instance)
- ✅ **Independent** of your Mac
- ✅ **Real cloud experience**
- ✅ **$5 under budget**

### Cons
- ❌ **AWS account required**
- ❌ **Setup time** (1-2 hours)
- ❌ **Need to manage server**
- ❌ **Limited resources** (2 GB RAM)
- ❌ **SSH management**

### Best For
- Production-like demo
- Learning cloud deployment
- When Mac isn't available

---

## Option 4: **AWS EC2 + ngrok/Cloudflare**

### Architecture
```
AWS EC2 → ngrok/Cloudflare → Custom URL → Reviewers
```

### Setup
```bash
# EC2 instance (t3.micro - FREE)
# + ngrok for custom domain
ngrok http 8000 --subdomain novareel-demo
```

### Costs
| Service | Cost/Month |
|---|---|
| EC2 t3.micro | $0 (750 hrs free) |
| ngrok (paid) | $5 |
| Data transfer | ~$5 |
| **Total** | **~$10** |

### Pros
- ✅ **Free EC2 instance**
- ✅ **Custom domain** (novareel-demo.ngrok.io)
- ✅ **Professional hosting**
- ✅ **$20 under budget**
- ✅ **Independent of Mac**

### Cons
- ❌ **More complex** (EC2 + tunnel)
- ❌ **Two services to manage**
- ❌ **Still need AWS account**

### Best For
- Custom domain on budget
- Learning both AWS and tunneling

---

## Option 5: **Hybrid (Frontend Vercel + Backend EC2)**

### Architecture
```
Frontend: Vercel (free) → Backend: EC2 → Reviewers
```

### Setup
```bash
# Deploy frontend to Vercel
npm run build
vercel --prod

# Backend on EC2
# Update NEXT_PUBLIC_API_BASE_URL
```

### Costs
| Service | Cost/Month |
|---|---|
| Vercel (frontend) | $0 |
| EC2 t3.small | $20 |
| **Total** | **~$20** |

### Pros
- ✅ **Optimal frontend performance** (Vercel CDN)
- ✅ **Backend control** (EC2)
- ✅ **$10 under budget**
- ✅ **Professional setup**

### Cons
- ❌ **Two deployments** to manage
- ❌ **More complex** setup
- ❌ **Need to configure CORS**

### Best For
- Best user experience
- Production-like architecture

---

## Decision Matrix

| Factor | ngrok Free | Cloudflare | EC2 t3.small | Hybrid |
|---|---|---|---|---|
| **Cost** | $5-10 | $5-10 | $25 | $10-20 |
| **Setup Time** | 5 min | 10 min | 2 hrs | 3 hrs |
| **URL Stability** | ❌ Changes | ✅ Persistent | ✅ Static IP | ✅ Custom |
| **Reliability** | Home net | Home net | AWS | AWS |
| **Professional** | ❌ Demo | ❌ Demo | ✅ Prod | ✅ Prod |
| **Mac Required** | ✅ Yes | ✅ Yes | ❌ No | ❌ No |
| **Learning Value** | Low | Low | High | High |

---

## Recommendations by Scenario

### **For Hackathon (Immediate)**
**Winner: Cloudflare Tunnel**
- Free, persistent URL
- 10-minute setup
- Professional appearance

### **For Learning Cloud**
**Winner: EC2 t3.small**
- Real cloud experience
- Production-like
- $25 within budget

### **For Best Demo**
**Winner: Hybrid (Vercel + EC2)**
- Fast frontend (CDN)
- Reliable backend
- $20 under budget

### **For Zero Budget**
**Winner: ngrok Free**
- Absolutely no cost
- Instant setup
- URL changes (acceptable for demo)

---

## Next Steps

1. **Choose your option** based on priorities
2. **I'll provide detailed setup instructions**
3. **Test with a small group** before hackathon
4. **Have backup plan** (URL changes, downtime)

Which option interests you most? I can walk through the exact setup steps.
