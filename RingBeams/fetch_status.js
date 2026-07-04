// Ring Beams / Alarm status fetcher (ESM).
// One-shot: connects via socket.io, dumps all sensor devices with battery /
// tamper / faulted state to stdout as JSON, exits.
//
// Env vars (required):
//   RING_BEAMS_TOKEN_FILE  path to refresh-token file. Two formats accepted:
//     - plain refresh_token string
//     - Python ring-doorbell OAuth JSON dict (extracts .refresh_token)
//
// stdout: {"devices": [{zid, name, deviceType, categoryId, batteryLevel,
//                       batteryStatus, tamperStatus, faulted, locationName}, ...]}
// stderr: {"error": "<msg>"} on failure; exit code 1..3 signals class of error.
import { RingApi } from 'ring-client-api';
import fs from 'node:fs';

const tokenFile = process.env.RING_BEAMS_TOKEN_FILE;
if (!tokenFile) {
    console.error(JSON.stringify({ error: 'RING_BEAMS_TOKEN_FILE env var required' }));
    process.exit(2);
}

function readRefreshToken(path) {
    const raw = fs.readFileSync(path, 'utf-8').trim();
    if (raw.startsWith('{')) {
        const parsed = JSON.parse(raw);
        if (!parsed.refresh_token) throw new Error('JSON token missing refresh_token');
        return parsed.refresh_token;
    }
    return raw;
}

function writeRefreshToken(path, token) {
    // Preserve Python-style JSON envelope if the file currently holds a dict.
    let payload = token;
    try {
        const raw = fs.readFileSync(path, 'utf-8').trim();
        if (raw.startsWith('{')) {
            const parsed = JSON.parse(raw);
            parsed.refresh_token = token;
            payload = JSON.stringify(parsed);
        }
    } catch (_) {
        // fall through: write plain token
    }
    fs.writeFileSync(path, payload, { mode: 0o600 });
}

async function main() {
    let refreshToken;
    try {
        refreshToken = readRefreshToken(tokenFile);
    } catch (e) {
        console.error(JSON.stringify({ error: `token read failed: ${e.message}` }));
        process.exit(3);
    }

    const ring = new RingApi({
        refreshToken,
        controlCenterDisplayName: 'homely-vibes-beams',
    });

    ring.onRefreshTokenUpdated.subscribe(({ newRefreshToken }) => {
        if (newRefreshToken) {
            try {
                writeRefreshToken(tokenFile, newRefreshToken);
            } catch (_) {
                // best effort; next run will retry
            }
        }
    });

    let locations;
    try {
        locations = await ring.getLocations();
    } catch (e) {
        console.error(JSON.stringify({ error: `auth/list-locations failed: ${e.message}` }));
        process.exit(1);
    }

    const devices = [];
    const errors = [];
    for (const loc of locations) {
        let locDevices;
        try {
            locDevices = await loc.getDevices();
        } catch (e) {
            // Include in payload — Python surfaces to Pushover so a partial failure
            // is never masked as "all healthy" (exit=0 with missing devices).
            errors.push(`getDevices(${loc.name}): ${e.message}`);
            continue;
        }
        for (const d of locDevices) {
            const x = d.data;
            devices.push({
                zid: x.zid,
                name: x.name,
                deviceType: x.deviceType,
                categoryId: x.categoryId,
                batteryLevel: x.batteryLevel ?? null,
                batteryStatus: x.batteryStatus ?? null,
                tamperStatus: x.tamperStatus ?? null,
                faulted: x.faulted ?? null,
                locationName: loc.name,
            });
        }
    }

    process.stdout.write(JSON.stringify({ devices, errors }) + '\n');
    process.exit(0);
}

main().catch((err) => {
    console.error(JSON.stringify({ error: `unhandled: ${err && err.message ? err.message : String(err)}` }));
    process.exit(1);
});
