import sys
import re

with open(r'c:\Users\LENOVO\Desktop\Git-Projects\PromptMatrix-Private\static\index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove ROW 1
start_row1 = content.find('<!-- ── ROW 1: Waitlist tiers ── -->')
end_row1 = content.find('<!-- ── ROW 2: Community + Founder (live) + Enterprise ── -->')
if start_row1 != -1 and end_row1 != -1:
    content = content[:start_row1] + content[end_row1:]

# Replace grid for ROW 2
grid_old = '<div style="display:grid;grid-template-columns:1fr 1.2fr 1fr;gap:14px;margin-bottom:40px" class="pricing-grid">'
grid_new = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;max-width:800px;margin:0 auto 40px" class="pricing-grid">\n  <!-- ── Community + Founder (live) ── -->'
content = content.replace(grid_old, grid_new)
content = content.replace('<!-- ── ROW 2: Community + Founder (live) + Enterprise ── -->\n', '')

# Remove Enterprise
start_ent = content.find('<!-- ENTERPRISE -->')
end_ent = content.find('</div>\n\n  </div>\n\n  <!-- FEATURE COMPARISON TABLE (6-column) -->')
if start_ent != -1 and end_ent != -1:
    content = content[:start_ent] + content[end_ent:]

# Fix table headers
content = content.replace('<!-- FEATURE COMPARISON TABLE (6-column) -->', '<!-- FEATURE COMPARISON TABLE (3-column) -->')

# Remove the three THs
th1 = '<th style="text-align:center;padding:12px 10px;color:rgba(124,106,247,.7);font-size:8px;letter-spacing:.15em;font-weight:400;border-left:1px solid var(--b)">STARTER</th>'
th2 = '<th style="text-align:center;padding:12px 10px;color:rgba(0,200,255,.7);font-size:8px;letter-spacing:.15em;font-weight:400;border-left:1px solid var(--b)">PRO</th>'
th3 = '<th style="text-align:center;padding:12px 10px;color:rgba(255,160,0,.7);font-size:8px;letter-spacing:.15em;font-weight:400;border-left:1px solid var(--b)">SCALE</th>'
content = content.replace(f"{th1}\n          {th2}\n          {th3}\n          ", "")

# Remove the three TDs in each row
content = re.sub(r'<td style="text-align:center;padding:10px 10px;color:var\(--txt[23]?\);border-left:1px solid var\(--b\)">.*?</td>\n          <td style="text-align:center;padding:10px 10px;color:var\(--txt[23]?\);border-left:1px solid var\(--b\)">.*?</td>\n          <td style="text-align:center;padding:10px 10px;color:var\(--txt[23]?\);border-left:1px solid var\(--b\)">.*?</td>\n          ', '', content)

content = re.sub(r'<td style="text-align:center;padding:10px 10px;color:var\(--rd\);border-left:1px solid var\(--b\)">.*?</td>\n          <td style="text-align:center;padding:10px 10px;color:var\(--g\);border-left:1px solid var\(--b\)">.*?</td>\n          <td style="text-align:center;padding:10px 10px;color:var\(--g\);border-left:1px solid var\(--b\)">.*?</td>\n          ', '', content)

content = re.sub(r'<td style="text-align:center;padding:10px 10px;color:rgba\(124,106,247,.8\);border-left:1px solid var\(--b\)">.*?waitlist</span></td>\n          <td style="text-align:center;padding:10px 10px;color:rgba\(0,200,255,.8\);border-left:1px solid var\(--b\)">.*?waitlist</span></td>\n          <td style="text-align:center;padding:10px 10px;color:rgba\(255,160,0,.8\);border-left:1px solid var\(--b\)">.*?waitlist</span></td>\n          ', '', content)

with open(r'c:\Users\LENOVO\Desktop\Git-Projects\PromptMatrix-Private\static\index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done!")
