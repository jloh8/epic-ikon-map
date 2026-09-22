#!/usr/bin/env python3
"""Bake real OSM piste/lift geometry for all resorts into data/pistes/<slug>.json.

Uses the main OSM API (api.openstreetmap.org) with adaptive bbox tiling to stay
under the 50000-node limit. Output format matches what the app's parseOSM()
expects: {"elements":[{"type":"way","tags":{...},"geometry":[{"lat":..,"lon":..}]}]}.
The app tries the baked file first, then falls back to runtime Overpass.
"""
import re, json, time, sys, os
import urllib.request, urllib.error
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, 'data', 'pistes')
os.makedirs(OUTDIR, exist_ok=True)

UA = {'User-Agent': 'epic-ikon-map/1.0 (resort piste bake for ski atlas; github.com/jloh8/epic-ikon-map)'}

def slugify(n):
    return re.sub(r'[^a-z0-9]+', '-', n.lower()).strip('-')

def parse_resorts():
    html = open(os.path.join(REPO, 'index.html'), encoding='utf-8').read()
    out = []
    for m in re.finditer(r'\{name:"([^"]+)",pass:"(?:epic|ikon)",lat:([-\d.]+),lng:([-\d.]+)', html):
        out.append({'name': m.group(1), 'lat': float(m.group(2)), 'lng': float(m.group(3))})
    return out

def fetch_bbox(s, w, n, e):
    url = 'https://api.openstreetmap.org/api/0.6/map?bbox=%.5f,%.5f,%.5f,%.5f' % (w, s, e, n)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as ex:
        return ex.code, b''
    except Exception as ex:
        return -1, str(ex).encode()

def parse_ways(xml_bytes):
    """Return dict way_id -> (tags, [(lat,lon)...]) for piste/aerialway ways."""
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return {}
    nodes = {}
    for nd in root.iter('node'):
        try:
            nodes[nd.get('id')] = (float(nd.get('lat')), float(nd.get('lon')))
        except (TypeError, ValueError):
            pass
    ways = {}
    for w in root.iter('way'):
        tags = {}
        for t in w.iter('tag'):
            k, v = t.get('k'), t.get('v')
            if k in ('name', 'piste:type', 'piste:difficulty', 'aerialway'):
                tags[k] = v
        pt = tags.get('piste:type')
        if not ((pt in ('downhill', 'ski', 'glade')) or ('aerialway' in tags)):
            continue
        geom = []
        ok = True
        for nd in w.iter('nd'):
            c = nodes.get(nd.get('ref'))
            if c is None:
                ok = False
                break
            geom.append(c)
        if not ok or len(geom) < 2:
            continue
        ways[w.get('id')] = (tags, geom)
    return ways

def fetch_tiled(lat, lng, dlat, dlng, depth=0):
    """Fetch bbox, tiling into 2x2 on 400 (node limit). Returns merged ways dict."""
    s, n = lat - dlat, lat + dlat
    w, e = lng - dlng, lng + dlng
    status, body = fetch_bbox(s, w, n, e)
    time.sleep(2)
    if status == 200:
        return parse_ways(body)
    if status == 400 and depth < 2:
        merged = {}
        for qlat in (lat - dlat / 2, lat + dlat / 2):
            for qlng in (lng - dlng / 2, lng + dlng / 2):
                merged.update(fetch_tiled(qlat, qlng, dlat / 2, dlng / 2, depth + 1))
        return merged
    return {}

def main():
    resorts = parse_resorts()
    print('resorts:', len(resorts), flush=True)
    only = sys.argv[1:]  # optional slug filter
    done, skipped = 0, 0
    for r in resorts:
        slug = slugify(r['name'])
        if only and slug not in only:
            continue
        out = os.path.join(OUTDIR, slug + '.json')
        if os.path.exists(out):
            print('skip (exists)', slug, flush=True)
            continue
        ways = fetch_tiled(r['lat'], r['lng'], 0.035, 0.045)
        if not ways:
            print('NO DATA', slug, flush=True)
            skipped += 1
            continue
        elements = []
        for wid, (tags, geom) in ways.items():
            elements.append({
                'type': 'way',
                'tags': tags,
                'geometry': [{'lat': la, 'lon': lo} for la, lo in geom],
            })
        with open(out, 'w', encoding='utf-8') as f:
            json.dump({'elements': elements}, f, separators=(',', ':'))
        kb = os.path.getsize(out) // 1024
        print('baked', slug, len(elements), 'ways', kb, 'KB', flush=True)
        done += 1
    print('done:', done, 'skipped:', skipped, flush=True)

if __name__ == '__main__':
    main()
