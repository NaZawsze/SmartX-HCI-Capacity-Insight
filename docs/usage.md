# Usage Guide

This guide explains the main workflows in SmartX HCI Capacity Insight.

## 1. Login

Open:

```text
http://<server-ip>:8080
```

Default account:

```text
admin / password
```

Change the password after the first login.

## 2. Add a Tower

Open `Settings`, then add a Tower:

- Fill in a display name.
- Fill in the CloudTower/Tower URL.
- Use username/password or an optional API token.
- Keep TLS verification enabled unless the environment requires otherwise.
- Set the Tower-level collection time.

Click the connection test action after saving. A successful test discovers clusters and updates the sidebar tree.

## 3. Configure Clusters

After Tower discovery, clusters are listed under the Tower. You can:

- Enable or disable a cluster.
- Customize the cluster display name.
- Use the sidebar tree to select all data, one Tower, or one cluster.

The selected scope affects dashboard capacity overview and report data.

## 4. Run Collection

The platform supports:

- Daily scheduled collection based on Tower settings.
- Manual collection from the dashboard.

Collection status is shown at Tower level. If a collection is running, wait until it finishes before starting another manual collection.

## 5. Dashboard

The dashboard provides:

- Total capacity overview for the selected scope.
- Used capacity and total capacity.
- Tower and cluster count.
- Daily fastest-growing VMs.
- Tower-level collection state.

The daily fastest-growing VM ranking supports sorting by:

- Growth amount.
- Growth ratio.

Click a VM in the ranking to open the VM page and select the corresponding VM.

## 6. VM Page

The VM page includes:

- VM list.
- Search.
- Sorting by VM storage size.
- Sorting by guest storage usage ratio.
- Storage trend chart.
- Current VM volume details.
- All VM volume details.

Trend ranges:

```text
7 days, 14 days, 30 days, 90 days, 180 days, 365 days
```

The default trend view is 30 days. If fewer samples exist, the chart displays available samples.

Volume detail columns:

- Volume name.
- Actual used space.
- Provisioned space.
- Replica or redundancy policy when available.
- Actual cluster occupied space.

## 7. Reports

The reports page provides:

- Cluster forecast reports.
- Forecast sample window.
- Cluster total growth rate.
- Daily Top growing VMs.
- Monthly Top growing VMs.

Daily and monthly VM rankings display up to 50 VMs and support sorting by:

- Growth amount.
- Growth ratio.

Click a VM in either report ranking to open the VM page and select the corresponding VM.

The export action follows the current report scope:

- All clusters: exports all enabled clusters.
- Tower: exports clusters under the selected Tower.
- Cluster: exports only the selected cluster.

Click `Export`, select a historical window, then confirm. The page downloads both a Word document and an Excel workbook. The Word document contains a scope summary, cluster forecast summary, and per-cluster monthly Top 100 VM sections by growth amount and growth ratio. The Excel workbook contains a summary sheet, a combined VM Top 100 sheet, and one sheet per cluster. Export filenames include the scope name and date.

## 8. Forecast Meaning

The report uses recent samples to estimate growth trend:

- Sample window: selected export or page window, with 30 days as the default report window.
- Forecast horizon: 60 days.
- Forecast data may show insufficient data when there are too few samples.

The forecast is an operational estimate, not a replacement for capacity planning review.

## 9. Password Change

Open the admin avatar menu in the top-right corner, then choose `Set Password`.

You must provide:

- Current password.
- New password.
- Confirm new password.

If the password is lost, use the CLI reset command on the server:

```bash
cd /opt/smartx-storage-forecast
```

Interactive reset:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin
```

Non-interactive reset:

```bash
docker compose exec web-api python -m app.cli reset-password --username admin --password password
```

After reset, log out and log in again with the new password.
