"""OmniGauge mark - the raster generator. logo.svg is the authored source; this
draws the same three-gauge stack with PIL (glass cells in recessed sockets) at any
size and produced every PNG, favicon, the avatar, the X header and the OG image.
Run with Pillow; the banner text uses the same JetBrains Mono the site embeds.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
FIELD=(9,18,40); PANEL=(14,27,60); WHITE=(219,227,242); CYAN=(90,166,201); AMBER=(201,151,79); GRAY=(138,152,182)
RED=(196,112,112); GREEN=(110,168,136); FAINT=(46,62,104); FAINT_D=(30,42,74)
RED_L=(238,168,168); RED_D=(120,56,56); GREEN_L=(168,216,188); GREEN_D=(54,104,80); AMB_L=(238,204,140); AMB_D=(140,100,45)
SS=4
def vgrad(w,h,stops):
    g=Image.new('RGB',(1,h)); px=g.load()
    for y in range(h):
        t=y/max(1,h-1); i=min(int(t*(len(stops)-1)),len(stops)-2); lt=t*(len(stops)-1)-i
        a,b=stops[i],stops[i+1]; px[0,y]=tuple(int(a[k]+(b[k]-a[k])*lt) for k in range(3))
    return g.resize((w,h))
def cell(im,x,y,w,h,stops,shadow=True,rad=None):
    """A rendered gauge cell: gradient body, top highlight, thin rim, soft drop shadow."""
    W,H=im.size; rad=min(rad or 3*SS, w//2, h//2)
    def layer(): return Image.new('RGBA',(W,H),(0,0,0,0))
    if shadow:
        sh=layer(); ImageDraw.Draw(sh).rounded_rectangle([x+2*SS,y+5*SS,x+w+2*SS,y+h+5*SS],radius=rad,fill=(1,4,14,160))
        sh=sh.filter(ImageFilter.GaussianBlur(4*SS)); im.alpha_composite(sh)
    m=Image.new('L',(W,H),0); ImageDraw.Draw(m).rounded_rectangle([x,y,x+w,y+h],radius=rad,fill=255)
    body=layer(); body.paste(vgrad(w,h,stops).convert('RGBA'),(x,y)); body.putalpha(ImageChops.multiply(body.split()[3],m)); im.alpha_composite(body)
    # no rim, no highlight cap: the gradient alone carries the depth. Rims and
    # caps read as fussy little borders on the tiles - John's call.
def track(im,x,y,w,h,rad=None):
    """An empty cell: recessed - dark fill, an inner shadow line at the top."""
    rad=rad or 3*SS; d=ImageDraw.Draw(im); rad=min(rad,w//2,h//2)
    d.rounded_rectangle([x,y,x+w,y+h],radius=rad,fill=FAINT_D+(255,))
    if int(h*0.28)>1: d.rounded_rectangle([x,y,x+w,y+int(h*0.28)],radius=max(1,rad-1),fill=(1,4,14,60))
def stack(im,x0,y0,cw,ch,gap,rgap,rows,n=8):
    y=y0
    for pct,stops in rows:
        k=int(round(pct*n))
        for i in range(n):
            x=x0+i*(cw+gap)
            if i<k: cell(im,x,y,cw,ch,stops)
            else: track(im,x,y,cw,ch)
        y+=ch+rgap
ROWS=[(0.28,[GREEN_L,GREEN,GREEN_D]),(1.00,[RED_L,RED,RED_D]),(0.41,[GREEN_L,GREEN,GREEN_D])]
