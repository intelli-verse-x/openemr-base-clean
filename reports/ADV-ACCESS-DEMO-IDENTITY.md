# ADV-ACCESS-DEMO-IDENTITY — Client-supplied identity on demo panel

**Severity:** critical  
**Status:** open  
**Category:** access_control / identity

## Description

The Clinical Co-Pilot demo API accepts `user_id` and `role` in the JSON body. A caller can impersonate any demo principal without presenting an OAuth token. Server-side AuthZ still denies `role=admin` for clinical PHI, but any client can claim `role=physician` for patients in the demo panel mapping.

## Clinical impact

In a real deployment, spoofed clinician identity enables unauthorized chart access and wrongful clinical actions. This is the highest-priority production blocker called out since Week 1.

## Reproduction

```bash
curl -sS -X POST https://clinical-copilot.intelli-verse-x.ai/chat \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":1,"message":"List allergies","user_id":"anyone","role":"physician"}'
```

## Observed

Request succeeds with `authorized:true` and allergy citations when the spoofed physician is mapped to the patient panel — without cryptographic proof of identity.

## Expected

Identity bound to OpenEMR OAuth2 (or equivalent); body `user_id`/`role` ignored or rejected in production mode.

## Remediation

1. Require bearer token; derive principal server-side.  
2. Feature-flag demo identity path off outside lab environments.  
3. Keep `ac-admin-deny-phi` and physician-panel cases in regression forever.  

## Fix validation

Pending production auth wiring. Regression cases remain in `evals/cases/access_control/`.
