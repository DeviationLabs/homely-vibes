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
// Exit-code contract (stderr carries a JSON {"error": "..."} on 2/3/4/5; on
// exit 1 stderr is a raw Node stack trace with no JSON envelope):
//   0  success
//   1  uncaught Node crash / module-load failure (reserved for Node itself)
//   2  missing RING_BEAMS_TOKEN_FILE env var
//   3  token file unreadable / malformed         → auth-class
//   4  post-auth unhandled JS exception
//   5  auth / list-locations failure (bad token) → auth-class
// Python (beams_manager.run_sidecar) maps 3 and 5 to BeamsAuthError; every
// other non-zero code is a generic RuntimeError so a Node-version drift (e.g.
// undici requiring global File on Node <20) does NOT get misclassified as
// "Ring: Auth Required".
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
    // Atomic write: tmp file with 0o600 from birth, then rename over. Matches
    // lib/secure_io.write_secret_atomic — a partial or crashed write can never
    // leave the token file empty and page RingSecurity with invalid_grant.
    const tmp = `${path}.tmp.${process.pid}`;
    fs.writeFileSync(tmp, payload, { mode: 0o600 });
    fs.renameSync(tmp, path);
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
            } catch (e) {
                // Ring rotated server-side but our write failed — the file now
                // holds an already-consumed token. Surface loudly so the next
                // invalid_grant is diagnosable (Python's run_sidecar tees this
                // to stderr → cron log). Don't exit non-zero: we still have a
                // valid in-memory session and returning devices is more useful
                // than paging on a token-write hiccup.
                console.error(JSON.stringify({
                    warn: `TOKEN_WRITE_FAILED: ${e.message}`,
                    path: tokenFile,
                }));
            }
        }
    });

    let locations;
    try {
        locations = await ring.getLocations();
    } catch (e) {
        console.error(JSON.stringify({ error: `auth/list-locations failed: ${e.message}` }));
        process.exit(5);
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
            try {
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
            } catch (e) {
                // Malformed device — surface via errors, don't crash the whole run.
                errors.push(`parseDevice(${loc.name}): ${e.message}`);
            }
        }
    }

    // Drain before exit — process.exit(0) on a pipe can truncate writes
    // above ~16KB stdout high-water mark; a large installation (50+ devices)
    // would produce non-JSON on the Python side and mask device state.
    process.stdout.write(JSON.stringify({ devices, errors }) + '\n', () => {
        process.exit(0);
    });
}

main().catch((err) => {
    // Exit 4: post-auth unhandled failure (e.g. TypeError iterating a
    // malformed device). Python maps 1/3 → BeamsAuthError; using 4 avoids a
    // misleading "Auth Required" P2 when the real problem is a parsing bug.
    console.error(JSON.stringify({ error: `unhandled: ${err && err.message ? err.message : String(err)}` }));
    process.exit(4);
});
