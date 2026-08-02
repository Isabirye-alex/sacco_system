"""
HTML Email Template Builder for SACCO PRO notifications.
"""

def build_sacco_email_html(subject: str, body: str, sacco_name: str = "SACCO PRO") -> str:
    # Convert newlines into styled paragraphs
    lines = [p.strip() for p in body.split("\n") if p.strip()]
    if lines:
        content_html = "".join(f"<p style='margin:0 0 14px 0;line-height:1.6;'>{line}</p>" for line in lines)
    else:
        content_html = f"<p style='margin:0 0 14px 0;line-height:1.6;'>{body}</p>"

    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{subject}</title>
  <style type="text/css">
    body, p, div {{ font-family: verdana, geneva, sans-serif; font-size: 14px; color: #0a3752; }}
    body {{ margin: 0; padding: 0; background-color: #edf1f3; }}
    a {{ color: #487995; text-decoration: none; }}
  </style>
</head>
<body>
  <center style="width:100%;background-color:#edf1f3;padding:30px 0;">
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:600px;background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.05);margin:0 auto;text-align:left;">
      <!-- Header banner -->
      <tr>
        <td bgcolor="#0A3752" style="padding:25px 35px;background-color:#0A3752;">
          <div style="font-family:verdana, geneva, sans-serif;color:#84B0CA;font-size:12px;font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:6px;">{sacco_name}</div>
          <div style="font-family:verdana, geneva, sans-serif;color:#ffffff;font-size:20px;font-weight:bold;">{subject}</div>
        </td>
      </tr>
      <!-- Body Content -->
      <tr>
        <td bgcolor="#ffffff" style="padding:35px;font-family:verdana, geneva, sans-serif;font-size:15px;color:#0a3752;line-height:24px;">
          {content_html}
        </td>
      </tr>
      <!-- Footer -->
      <tr>
        <td bgcolor="#EDF1F3" style="padding:20px 35px;background-color:#EDF1F3;border-top:1px solid #84B0CA;font-family:verdana, geneva, sans-serif;font-size:11px;color:#84B0CA;text-align:center;">
          <p style="margin:0 0 6px 0;">This is an official automated notification from <strong>{sacco_name}</strong>.</p>
          <p style="margin:0;">&copy; 2026 {sacco_name}. All rights reserved.</p>
        </td>
      </tr>
    </table>
  </center>
</body>
</html>"""
