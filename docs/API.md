# Instant On API notes

These are notes on the **undocumented** Instant On portal API, as seen on a live site on 2026-10-16
(firmware 3.4.2 on AP-505 access points and JL681A/JL684A switches). HPE can change any of this.
The sign-in flow was first documented at <https://blog.puddle.town/instant-on/>.

## Discovery

`GET https://portal.instant-on.hpe.com/settings.json` (no authentication needed)

```json
{
  "restApiUrl": "https://portal.instant-on.hpe.com",
  "healthApiUrl": "https://health.portal.instant-on.hpe.com",
  "ssoRedirectUrl": "https://portal.instant-on.hpe.com",
  "ssoClientIdAuthZ": "<client id>",
  "ssoFqdn": "https://sso.arubainstanton.com",
  "featureFlags": { "federatedSSO": true }
}
```

## Authentication

| Step | Request | Response |
|---|---|---|
| 1 | `POST {ssoFqdn}/aio/api/v1/mfa/validate/full`, form: `username`, `password` | `200 {access_token, expires_in, success, token_type}`, or `400 {"error":"invalid_grant", ...}` |
| 2 | `GET {ssoFqdn}/as/authorization.oauth2` with `client_id`, `redirect_uri`, `response_type=code`, `scope=profile openid`, `state`, `code_challenge`, `code_challenge_method=S256`, `sessionToken` (don't follow redirects) | `302`, with `code` and `state` in the `Location` query string |
| 3 | `POST {ssoFqdn}/as/token.oauth2`, form: `client_id`, `redirect_uri`, `code`, `code_verifier`, `grant_type=authorization_code` | `200 {access_token, expires_in: 1799, id_token, refresh_token, scope, token_type}` |

## REST calls

All calls are `GET {restApiUrl}/api/...` with these headers:

```
Authorization: Bearer <access_token>
x-ion-api-version: 7
Accept: application/json
```

Lists come back as `{"elements": [...], "kind": ..., "totalCount": ..., ...}`.

| Endpoint | Used | Contents |
|---|---|---|
| `/api/sites/` | yes | Sites |
| `/api/sites/{id}/clientSummary` | yes | Wired and wireless clients, including recently disconnected ones |
| `/api/sites/{id}/inventory` | yes | APs and switches |
| `/api/sites/{id}/alerts` | no | Alerts (none were present, so the format wasn't seen) |
| `/api/sites/{id}/networksSummary` | no | Wi-Fi and wired network definitions |
| `/api/sites/{id}/wiredClientSummary` | n/a | **Removed (404)** |

## Key fields

### Site (`/api/sites/` elements)

`id`, `name`, `status` (`up`), `health` (`good`…), `healthReason`, `currentHealthScore.{score, scoreSeverity, conditionsCount}`,
`activeAlertsCount`, `activeAlertsCounters.{activeInfoAlertsCount, activeMinorAlertsCount, activeMajorAlertsCount}`,
`latestActiveAlert`, `latestAlert`, `timezoneIana`, `isMaintenanceMode`, `updateInProgress`, `userRoleOnSite`.

### Client (`clientSummary` elements)

| Field | Notes |
|---|---|
| `id`, `macAddress` | Client MAC (identical) |
| `name`, `hostName` | Friendly name; hostname |
| `status` | `up` = connected, `down` = recently disconnected but still listed |
| `clientType` | `wireless` / `wired` |
| `ipAddress` | Often `""` for wired clients |
| `deviceId`, `deviceName` | AP or switch the client is connected to |
| `connectedToPorts[]` | Wired only: `deviceName`, `portName`, `portNumber`, `portSpeed`, `duplex`, PoE flags |
| `wirelessNetworkId/Name`, `wirelessBand`, `wirelessRadioId` | Wireless only |
| `wiredNetworkId/Name` | Network (VLAN) name |
| `signalQuality`, `snrInDb`, `health` | Wireless quality |
| `stateDurationInSeconds` | Time in the current state |
| `dataTraffic`, `upstream/downstreamThroughputInBitsPerSecond` | Traffic counters |
| `isBlocked`, `isBlockable`, `isWatchlisted` | Client controls (read-only here) |

### Device (`inventory` elements)

| Field | Notes |
|---|---|
| `id`, `macAddress` | Device MAC (identical) |
| `name`, `defaultName` | User-set name; default name (the serial number) |
| `deviceType`, `deviceRole` | `accessPoint` / `switch` |
| `model`, `sku`, `serialNumber` | e.g. `AP-505` / `R4W01A` |
| `status`, `operationalState`, `health` | `up`, `active`, `good` |
| `uptimeInSeconds`, `numberOfSecondsSinceLastCommunication` | |
| `currentFirmwareVersion`, `deviceSoftwareVersion`, `isUpToDate` | |
| `uplinkDeviceName`, `uplinkDeviceMacAddress`, `uplinkDeviceDeviceId` | Upstream device. For the root switch, this is the router, which usually isn't an Instant On device. |
| `inputPowerSource`, `poePdClass` | How the device is powered (`poe`, `ac-dc`) and its PoE class |
| `poePseStatus`, `poePseNominalPowerInWatts`, `poePseConsumedPowerInWatts` | Switches: PoE status, budget and current draw (e.g. 124 W budget, 26 W used) |
| `radios[]` | APs, one per band (see below) |
| `ethernetPorts[]` | Switches, and APs with Ethernet ports (see below) |
| `wirelessNetworks[]` | SSIDs on the AP |
| `ipAddress`, `subnetMask`, `defaultGateway`, `primaryDns` | Management IP |

### Radio (`inventory[].radios[]`)

| Field | Example | Notes |
|---|---|---|
| `id` | `aa:bb:cc:…` | Radio BSSID; matches `wirelessRadioId` on clients |
| `band` | `5ghz` | `2.4ghz`, `5ghz`, `6ghz` |
| `channel`, `channelWidth` | `36`, `80mhz` | |
| `utilizationPercent` | `4` | Airtime use |
| `wirelessClientsCount` | `18` | Clients on this radio |
| `txPowerEirpInDbm`, `regulatoryMaxTxPowerEirpInDbm` | `26.5` | Transmit power and regulatory limit |

### Switch port (`inventory[].ethernetPorts[]`)

Status fields:

| Field | Example | Notes |
|---|---|---|
| `portNumber`, `faceplatePortNumber` | `14` | Use the faceplate number for display |
| `isLinkUp` | `true` | |
| `speed`, `maxSpeed`, `duplex` | `mbps1000`, `full` | Negotiated speed, port's maximum and duplex |
| `isUplink`, `isDedicatedUplink`, `isSfp` | | |
| `directlyConnectedDeviceId`, `directlyConnectedDeviceName`, `directlyConnectedDeviceModel` | `Core Switch` | Set when another Instant On device is on the port. The card uses this to label map links with a port number and speed. |
| `downstreamThroughputInBitsPerSecond`, `upstreamThroughputInBitsPerSecond` | `19312690` | Current port throughput; also in `portDataTraffic` |
| `downstreamDataTransferredInBytes`, `upstreamDataTransferredInBytes` | | Counters; `portDataTraffic` adds 24 h totals |
| `health`, `isLoopDetected`, `isLinkFlappingDetected` | `good` | |

PoE fields:

| Field | Example | Notes |
|---|---|---|
| `isPoeSupported` | `true` | |
| `isProvidingPower` | `true` | |
| `powerProvidedInMilliwatts`, `powerRequestedInMilliwatts` | `7300`, `15400` | |
| `poePseStatus` | `deliveringPower`, `searching` | |
| `supportedPoeType`, `negotiatedPoeType` | `poePlus`, `poe` | |
| `supportedPoeClass`, `negotiatedPoeClass` | `802.3af Class 3` | |

Configuration fields (`networkMapping`, `poePriority`, `usePoeSchedule`, `stormControlEnabled`, `effectiveConfiguration`, …) are
present but unused.

## Quirks

- **Wired client throughput is per port, not per client.** A wired client's throughput fields (top-level and `dataTraffic`) repeat the
  throughput of the switch port it's behind. On the test site, 7 clients behind one port each reported the same 23.2 Mb/s.
  To total traffic, group wired clients by `connectedToPorts[0].deviceId` and `portNumber` (see `overview.talkers()`).
- **Disconnected clients stay listed.** `clientSummary` includes clients with `status: "down"` for a while after they leave.
- **IDs are MACs.** `id` is the MAC address for clients, devices and radios.
- **No IPs for most wired clients.** `ipAddress` is `""`.
