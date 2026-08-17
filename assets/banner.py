# OmniGauge X header + OG image generator. Every row is measured; the gap between the widest text and the panel is asserted. Run with Pillow + JetBrains Mono TTF beside it.
import sys; sys.path.insert(0, __import__('os').path.dirname(__file__))
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from render import *
CYAN=(90,166,201); AMBER=(201,151,79); GRAY=(138,152,182); DIM=(118,134,170); WHITE=(219,227,242); PANEL=(14,27,60); EDGE=(34,52,95); SHADOW=(1,4,14)
W,H=1500,500; C=SS
F=lambda px: ImageFont.truetype('jbmono.ttf',px)
im=Image.new('RGBA',(W*C,H*C),FIELD+(255,))
def glow(cx,cy,rx,ry,col,a):
    g=Image.new('RGBA',(W*C,H*C),(0,0,0,0)); ImageDraw.Draw(g).ellipse([cx-rx,cy-ry,cx+rx,cy+ry],fill=col+(a,)); return g.filter(ImageFilter.GaussianBlur(70*C))
im.alpha_composite(glow(300*C,250*C,320*C,260*C,(28,60,110),150)); im.alpha_composite(glow(1150*C,250*C,320*C,240*C,(20,44,90),110))
sl=Image.new('RGBA',(W*C,H*C),(0,0,0,0)); sd=ImageDraw.Draw(sl)
for y in range(0,H*C,4*C): sd.rectangle([0,y,W*C,y+C],fill=(255,255,255,4))
im.alpha_composite(sl)
s=1.45; x0=56*C; y0=int((H*C-126*s*C)/2)
stack(im,x0,y0,int(16*s*C),int(30*s*C),int(5*s*C),int(18*s*C),ROWS)
d=ImageDraw.Draw(im)
f=F(76*C); tx=350*C; ty=160*C
d.text((tx,ty),"Omni",font=f,fill=WHITE+(255,)); d.text((tx+f.getlength("Omni"),ty),"Gauge",font=f,fill=CYAN+(255,))
ft=F(25*C); d.text((tx+5*C,262*C),"every AI plan you pay for",font=ft,fill=GRAY+(255,)); d.text((tx+5*C,298*C),"on one screen",font=ft,fill=GRAY+(255,))
tag_right=max(tx+5*C+ft.getlength("every AI plan you pay for"), tx+f.getlength("OmniGauge"))  # widest text, not just the tagline
IN=45; fp=F(21*C); cw=fp.getlength("0"); lh=32*C; B=CYAN
def L(segs): return sum(len(t) for t,_ in segs)
def head(t,sub): l=[("╔══",B),("▌ ",B),(t,WHITE),(" ▐",B)]; r=[(" "+sub+" ",GRAY),("╗",B)]; return l+[("═"*(IN+3-L(l)-L(r)),B)]+r
def row(*segs): inner=list(segs); n=L(inner); assert n<=IN+1,(n,segs); return [("║",B)]+inner+[(" "*(IN+1-n),GRAY),("║",B)]
def foot(n): s_=[(" "+n+" ",GRAY)]; return [("╚══",B)]+s_+[("═"*(IN+3-3-L(s_)-1),B),("╝",B)]
def bar(pct,w,col):
    full=int(round(pct/100*w)); full=max(1,full) if pct>0 else 0; cap="▌" if 0<full<w else ""
    return [("█"*full+cap,col),("░"*(w-full-len(cap)),FAINT)]
Q='"'
rows=[head("PLAN QUOTA","normalized to % consumed"),row(),
      row(("   ● ",GREEN),("claude   ",WHITE),*bar(28,14,GREEN),("   28%",WHITE),("   4d 09h",GRAY)),
      row(),
      row(("   ● ",RED),  ("codex    ",WHITE),*bar(100,14,RED),("  100%",RED),("   4d 14h",GRAY)),
      row(("       ",GRAY),("said "+Q+"0% left"+Q+" - inverted",GRAY)),
      row(),
      row(("   ● ",GREEN),("grok     ",WHITE),*bar(41,14,GREEN),("   41%",WHITE),("   2d 04h",GRAY)),
      row(),foot("real readings · one machine")]
assert {L(r) for r in rows}=={IN+3}, {L(r) for r in rows}
cols=IN+3; fw=cols*cw+2*C; fh=len(rows)*lh+8*C
px=int(W*C-fw-50*C); py=int((H*C-fh)/2); gap=(px-tag_right)/C; assert gap>40, gap
d.rectangle([px+10*C,py+8*C,px+10*C+fw,py+8*C+fh],fill=SHADOW+(255,)); d.rectangle([px-2*C,py-2*C,px-2*C+fw,py-2*C+fh],fill=PANEL+(255,),outline=EDGE+(255,),width=C)
for i,r in enumerate(rows):
    xx=px
    for t,c in r:
        for ch in t: d.text((xx,py+2*C+i*lh),ch,font=fp,fill=c+(255,)); xx+=cw
out=im.resize((W,H),Image.LANCZOS).convert('RGB'); out.save('x-header-1500x500.png')
og=Image.new('RGB',(1200,630),FIELD); og.paste(out.resize((1200,400),Image.LANCZOS),(0,115)); og.save('../site/og.png')
print('og banner: gap', int(gap), 'px')
