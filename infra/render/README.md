# Free Render infrastructure

This service uses only `plan = "free"`, one instance, no disk, no hosted database,
and no paid inference calls. Frozen SQLite data and the ANN index ship in the
image. Runtime metadata edits are not persisted; the public API is read only.

Use either Terraform or the root `render.yaml` Blueprint as the configuration
owner. Do not apply both to create the same service. A service created through
the Render connector can be imported before Terraform takes ownership:

```sh
export RENDER_API_KEY=...  # securely in your local shell; never commit it
terraform init
terraform import -var='workspace_id=tea-dbb5bjnavr4c73fvbs30' render_web_service.demo SERVICE_ID
terraform plan -var='workspace_id=tea-dbb5bjnavr4c73fvbs30'
```

Review a plan before applying. The provider reads the API key from the environment.
State can contain sensitive configuration; use private state storage and keep
state files out of Git. `prevent_destroy` avoids accidental removal through this
configuration. Keep the workspace without a payment method before a public
deploy; this makes Render suspend at free usage limits instead of charging
overages. Pipeline spend limits cover builds, not every bandwidth charge.
The user confirmed no payment method is attached. No paid account upgrade is authorized.

Free service limits: 512 MB RAM, fractional CPU, idle sleep, ephemeral storage,
and a shared monthly free-hours quota. Local memory validation is evidence for
capacity, not proof of Linux container or hosted memory use. Verify the deployed
service and record observed resource use before marking Section 6 complete.

Provider schema: https://github.com/render-oss/terraform-provider-render
Free limits: https://render.com/docs/free
