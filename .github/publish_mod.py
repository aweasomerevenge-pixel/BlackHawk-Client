"""Publish only the BlackHawk mod JAR to the launcher release (pack-current), from any machine with `gh`.

Mirrors tools/publish-github.ps1 -ModOnly:
  * downloads the live manifest.json and checks its digest against the release asset,
  * changes only the mods/blackhawk-1.0.0.jar entry (all other entries preserved),
  * uploads the JAR as immutable asset bh-<sha256> (skipped if it already exists with that digest),
  * uploads the new manifest as manifest.staged-<sha>.json, then renames the old manifest to
    manifest.previous-<old12>-<rand>.json and the staged one to manifest.json,
  * downloads the published manifest and JAR back and verifies their SHA-256.

Usage: python3 publish_mod_cloud.py JAR [--repo OWNER/REPO] [--publish]
Without --publish nothing is changed (dry run).
"""
import argparse, hashlib, json, os, secrets, subprocess, sys, tempfile, urllib.request

ENTRY = 'mods/blackhawk-1.0.0.jar'
TAG = 'pack-current'


def gh(*args, data=None):
    r = subprocess.run(['gh', *args], input=data, capture_output=True)
    if r.returncode:
        raise RuntimeError('gh ' + ' '.join(args[:3]) + ' failed: ' + r.stderr.decode(errors='replace')[-800:])
    return r.stdout


def release(repo):
    return json.loads(gh('api', f'repos/{repo}/releases/tags/{TAG}'))


def asset_bytes(repo, asset_id):
    return gh('api', '-H', 'Accept: application/octet-stream', f'repos/{repo}/releases/assets/{asset_id}')


def upload(repo, release_id, name, path):
    out = gh('api', '-X', 'POST', '-H', 'Content-Type: application/octet-stream',
             f'https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={name}',
             '--input', path)
    return json.loads(out)


def rename(repo, asset_id, name):
    gh('api', '-X', 'PATCH', f'repos/{repo}/releases/assets/{asset_id}', '-f', f'name={name}', '--silent')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('jar')
    ap.add_argument('--repo', default='aweasomerevenge-pixel/BlackHawk-Client')
    ap.add_argument('--publish', action='store_true')
    o = ap.parse_args()

    jar = open(o.jar, 'rb').read()
    jar_sha = sha(jar)
    rel = release(o.repo)
    assets = {a['name']: a for a in rel['assets']}
    live = assets.get('manifest.json')
    if not live:
        raise SystemExit('No manifest.json in the release.')
    manifest_raw = asset_bytes(o.repo, live['id'])
    old_sha = sha(manifest_raw)
    if live.get('digest') and live['digest'] != 'sha256:' + old_sha:
        raise SystemExit('Downloaded manifest does not match its asset digest.')
    manifest = json.loads(manifest_raw)
    entries = [f for f in manifest['files'] if f['path'] == ENTRY]
    if manifest.get('version') != 1 or len(manifest['files']) < 2 or len(entries) != 1:
        raise SystemExit('Manifest must contain exactly one BlackHawk mod entry.')
    entry = entries[0]
    print(f'live mod {entry["sha256"][:12]}…  new mod {jar_sha[:12]}…  entries {len(manifest["files"])}')
    if entry['sha256'] == jar_sha and entry['size'] == len(jar):
        print('Already published: nothing to do.')
        return
    entry['sha256'] = jar_sha
    entry['size'] = len(jar)
    new_raw = json.dumps(manifest, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    new_sha = sha(new_raw)
    print(f'Updating 1 path. All other {len(manifest["files"]) - 1} entries preserved.')
    if not o.publish:
        print('DRY RUN: nothing uploaded.')
        return

    tmp = tempfile.mkdtemp(prefix='bh-publish-')
    name = 'bh-' + jar_sha
    if name in assets:
        if assets[name].get('digest') not in (None, 'sha256:' + jar_sha):
            raise SystemExit('Existing immutable mod asset has an unexpected digest.')
    else:
        p = os.path.join(tmp, name)
        open(p, 'wb').write(jar)
        upload(o.repo, rel['id'], name, p)
        print('uploaded', name)

    staged = f'manifest.staged-{new_sha}.json'
    rel = release(o.repo); assets = {a['name']: a for a in rel['assets']}
    if staged not in assets:
        p = os.path.join(tmp, staged)
        open(p, 'wb').write(new_raw)
        upload(o.repo, rel['id'], staged, p)
    rel = release(o.repo); assets = {a['name']: a for a in rel['assets']}
    st, cur = assets.get(staged), assets.get('manifest.json')
    if not st or st.get('digest') != 'sha256:' + new_sha:
        raise SystemExit('Staged manifest digest mismatch. Live manifest was not changed.')
    if not cur or cur['id'] != live['id'] or cur.get('digest') != 'sha256:' + old_sha:
        raise SystemExit('Another publisher changed the manifest. Nothing replaced.')
    backup = f'manifest.previous-{old_sha[:12]}-{secrets.token_hex(4)}.json'
    rename(o.repo, live['id'], backup)
    try:
        rename(o.repo, st['id'], 'manifest.json')
    except Exception:
        now = {a['name']: a for a in release(o.repo)['assets']}
        if 'manifest.json' not in now:
            rename(o.repo, live['id'], 'manifest.json')
            raise SystemExit('Manifest promotion failed; previous manifest restored.')
        raise

    # verify what players will download
    final = {a['name']: a for a in release(o.repo)['assets']}
    man = final['manifest.json']
    if man.get('digest') != 'sha256:' + new_sha:
        raise SystemExit('Published manifest digest could not be verified.')
    base = f'https://github.com/{o.repo}/releases/download/{TAG}/'
    got = json.loads(urllib.request.urlopen(base + 'manifest.json').read())
    e = [f for f in got['files'] if f['path'] == ENTRY][0]
    remote = urllib.request.urlopen(base + name).read()
    assert e['sha256'] == jar_sha == sha(remote) and len(remote) == len(jar), 'public download mismatch'
    print('Previous manifest preserved as:', backup)
    print('Published and verified:', base + 'manifest.json')


if __name__ == '__main__':
    main()
