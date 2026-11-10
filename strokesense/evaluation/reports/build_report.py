from pathlib import Path
import json, math
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from pypdf import PdfReader
R=Path(__file__).resolve().parents[2]
E=R/'evaluation'; OUT=Path(__file__).with_name('StrokeSense_Overnight_Improvement_Report.pdf')
D=json.loads((E/'tracking/results.json').read_text())['segments']
N=sum(v['sampled_frames']*8 for v in D.values()); B=sum(v['baseline']['observed_seat_frames'] for v in D.values()); A=sum(v['candidate']['observed_seat_frames'] for v in D.values())
NAVY=HexColor('#102B3D'); TEAL=HexColor('#087F8C'); GRAY=HexColor('#536775'); LIGHT=HexColor('#EDF4F6'); OLD=HexColor('#A8B6BE'); LINE=HexColor('#D7E2E7'); AMBER=HexColor('#9C5A17')
c=canvas.Canvas(str(OUT),pagesize=(612,792)); c.setTitle('StrokeSense | Overnight Improvement Report');c.setAuthor('StrokeSense development report')
W=516
styles={}
for name,size,lead,color in [('body',10.5,15,NAVY),('small',8.5,12,GRAY),('caption',9,12,GRAY),('label',9,12,TEAL)]:
 styles[name]=ParagraphStyle(name,fontName='Helvetica',fontSize=size,leading=lead,textColor=color,spaceAfter=0)
def p(text,y,x=48,w=W,style='body'):
 q=Paragraph(text,styles[style]);_,h=q.wrap(w,1000);q.drawOn(c,x,y-h);return y-h

def page(n,kicker,title,subtitle=''):
 c.setFillColor(TEAL);c.rect(0,786,612,6,fill=1,stroke=0)
 c.setFont('Helvetica-Bold',10);c.setFillColor(NAVY);c.drawString(48,757,'STROKESENSE')
 c.setFont('Helvetica',9);c.setFillColor(GRAY);c.drawRightString(564,757,'Overnight improvement report | 10 Nov 2026')
 c.setStrokeColor(LINE);c.line(48,741,564,741)
 c.setFillColor(TEAL);c.setFont('Helvetica-Bold',9);c.drawString(48,718,kicker.upper())
 c.setFillColor(NAVY);c.setFont('Helvetica-Bold',25);c.drawString(48,682,title)
 y=659
 if subtitle:y=p(subtitle,y,style='body')-20
 c.setStrokeColor(LINE);c.line(48,43,564,43)
 c.setFillColor(GRAY);c.setFont('Helvetica',8);c.drawString(48,28,'Core tracking and analysis only | Work paused at user request');c.drawRightString(564,28,f'{n} / 6')
 return y

def h(text,y):
 c.setFont('Helvetica-Bold',13);c.setFillColor(NAVY);c.drawString(48,y,text);return y-13

def table(rows,y,widths,header=True):
 data=[[Paragraph(str(v),styles['small' if i==0 and header else 'body']) for v in row] for i,row in enumerate(rows)]
 t=Table(data,colWidths=widths,hAlign='LEFT');t.setStyle(TableStyle([
 ('BACKGROUND',(0,0),(-1,0),LIGHT if header else white),('VALIGN',(0,0),(-1,-1),'TOP'),
 ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
 ('LINEBELOW',(0,0),(-1,0),.6,LINE),('LINEBELOW',(0,1),(-1,-1),.35,LINE)]))
 _,height=t.wrap(W,1000);t.drawOn(c,48,y-height);return y-height-16

def note(text,y):
 q=Paragraph(text,styles['small']);_,ht=q.wrap(W-24,1000);c.setFillColor(LIGHT);c.roundRect(48,y-ht-20,W,ht+20,6,fill=1,stroke=0);q.drawOn(c,60,y-ht-10);return y-ht-34

def end():c.showPage()

# 1
y=page(1,'Results at a glance','More reliable rowing measurements', 'The strongest gains are steadier seat tracking, better selection of complete body poses, and more defensible stroke timing. The app\'s UI and offering were not changed.')
for x,val,label in [(48,f'{A/N:.1%}','tracking coverage after'),(224,'+619','observed seat-frames'),(400,'808','regression tests run')]:
 c.setFillColor(LIGHT);c.roundRect(x, y-90,164,90,7,fill=1,stroke=0);c.setFillColor(TEAL);c.setFont('Helvetica-Bold',29);c.drawString(x+13,y-36,val);p(label,y-53,x+13,140,'small')
y-=120
y=h('What changed overnight',y)
for title,text in [
 ('Tracking stays with the rower','An ordered seat tracker uses hip position and shared boat/camera movement to reduce missing tracks and seat mix-ups.'),
 ('Body poses survive crop boundaries','A complete, stronger torso estimate can replace a truncated duplicate. This fixes a reproduced hip/knee collapse in clear footage.'),
 ('Motion and timing use stronger evidence','Confidence-aware body filtering, consistent fractional event times, supported hand-based finishes, and one-use crew catch matching improve the analysis core.')]:
 y=p(f'<b>{title}</b><br/>{text}',y)-17
y=note('<b>Measured scope.</b> Coverage rose from 90.2% to 96.0% on five cached boat segments from three supplied videos. This is tracking availability, not a claim that 96% of joints or strokes are correct. [1]',y)
y=p('<b>Status at handoff:</b> changes and reproducible evaluations are saved locally. Fresh inference-to-report runs completed. Neural weights were not retrained; the work improves detection postprocessing, tracking and analysis around the existing pose model.',y)
end()

# 2
y=page(2,'Measured tracking gains','Fewer gaps; more stable seat identity','The same cached detections were fed to the original and revised tracking paths, isolating tracking changes from new inference. [1]')
rows=[['Footage segment','Before','After','Change']]
for name,v in D.items():
 den=v['sampled_frames']*8;b=v['baseline']['observed_seat_frames']/den*100;a=v['candidate']['observed_seat_frames']/den*100
 rows.append([name.replace('-boat',' / boat '),f'{b:.1f}%',f'{a:.1f}%',f'{a-b:+.1f} pp'])
rows.append(['<b>All five segments</b>',f'<b>{B/N:.1%}</b>',f'<b>{A/N:.1%}</b>',f'<b>+{(A-B)/N*100:.1f} pp</b>'])
y=table(rows,y,[218,94,94,110])
y=p(f'The tracker retained <b>{A:,} of {N:,}</b> possible seat-frame observations, up from <b>{B:,}</b>. Missing observations fell from {N-B:,} to {N-A:,}, a <b>{(A-B)/(N-B):.0%} reduction</b>. No predicted position is counted as a detected observation.',y)-22
y=h('Small visual identity audit',y)
y=table([['Across 20 frames / 160 seat checks','Before','After'],['Correctly assigned','141','153'],['Wrong-seat assignments','3','0'],['Missing assignments','16','7']],y,[308,104,104])
y=note('<b>Tradeoffs and limits.</b> Improvements were not uniform. The second 9674 segment lost 1.7 percentage points of coverage. In the first 9674 visual subset, two previously correct observations became missing. The audit was assistant-reviewed, selected for development, and not independently labeled.',y)
p('pp means percentage points; changes use unrounded values. The largest gain came on the difficult, distant 0185 first-boat segment: 62.4% to 96.4%. Cleaner footage had less room to improve. These segment results predate the final crop-boundary detector fix; they should not be presented as a fresh benchmark of the entire final pipeline.',y,style='small')
end()

# 3
y=page(3,'Body pose correction','A complete body beats a cropped torso','A reproduced failure showed that person-detection confidence could favor a crop cutting through the rower over a more complete body estimate. [2]')
img=R/'results/body-motion-evaluation/crop-edge-comparison/torso-comparison.jpg'
height=W*760/1040;c.drawImage(str(img),48,y-height,width=W,height=height);y-=height+12
y=p('<b>Left:</b> previous duplicate selection. <b>Right:</b> revised selection on the same raw proposals. Red points and green links show the selected pose. The complete crop restores hip and knee locations to the visible body. Two consecutive sampled frames from IMG_9674 are shown.',y,style='caption')-19
y=p('The revised rule acts only after an anatomical same-person match. A complete alternative must have comparable person confidence and materially stronger shoulder/hip confidence. It keeps one whole pose and retains partial-only detections when no suitable replacement exists.',y)-15
y=note('<b>Observed result.</b> The two selected torso estimates changed from about -15 degrees to -36/-33 degrees, removing a crop-induced jump of roughly 17-20 degrees. This is a targeted failure correction, not a measured reduction in general angle error. Detection counts stayed unchanged across 12 replayed frames; six existing arm-audit predictions were unchanged.',y)
end()

# 4
y=page(4,'Motion and rowing analysis','More precise signals and phase timing','The core now handles confidence, gaps and event clocks more consistently. The numerical gains below come from controlled tests, not independent real-video labels.')
y=h('Body-motion conditioning',y)
y=p('Body shape is filtered relative to the hip, so shared camera movement does not become artificial joint movement. A fixed anatomical side avoids frame-by-frame left/right splicing. Isolated, well-supported joint jumps are rejected; interpolated gaps remain explicitly marked as estimates.',y)-15
y=table([['Controlled noisy-motion test [3]','Before RMSE','After RMSE'],['Trunk angle','3.29 degrees','2.14 degrees'],['Elbow angle','8.72 degrees','5.75 degrees'],['Thigh angle','3.95 degrees','2.48 degrees'],['Hand position, torso lengths','0.0549','0.0349']],y,[270,123,123])
y=p('RMSE is root-mean-square error; lower is better. These rows average six rate/frame-rate settings with confidence-dependent simulated noise. The full benchmark contains 24 conditions. Clean trunk motion was unchanged in that benchmark; simulated confidence/noise correlation is an assumption.',y,style='small')-23
y=h('Stroke and crew timing',y)
for title,txt in [
 ('One event clock','Rate, drive and recovery durations now use consistent fractional catch/finish times. Ideal-signal rate error from frame quantization fell from 0.425 to 0.00171 spm across 12 cases. This tests numerical precision only. [4]'),
 ('Finish follows supported hand motion','Knee extension can remain flat into recovery. Where local hand evidence is sufficient, hand reversal determines finish. Source review found and corrected gross late finishes on two videos; flat or blurred hand motion still limits exact timing. [5]'),
 ('Missing data and synchrony','Rhythm preserves the real sample clock instead of compressing gaps. Crew catches require a strict majority of distinct identities; each catch is used once. Insufficient support clears or withholds the timing score. [6]')]:
 y=p(f'<b>{title}.</b> {txt}',y)-13
y=p('Coincident or nonfinite joint endpoints now yield unavailable angles rather than fabricated 90-degree or upright measurements. No ideal rowing form or fixed limb length is imposed.',y,style='small')
end()

# 5
y=page(5,'Verification and restraint','Validation and experiment results','Changes were checked with targeted regressions, controlled motion, cached-footage comparisons, source-frame review and fresh full-pipeline runs.')
y=h('Validation at the pause point',y)
y=p('<b>808 tests ran: 798 passed, 10 failed.</b> The ten failures match pre-existing application/job/upload/web issues; no new failures were found. This is not an all-green suite. All four standalone legacy rowing/fault checks also passed. [7]',y)-16
y=table([['Fresh pipeline run','Output diagnostics','Result'],['IMG_9673 / 20 seconds','8 rowers; 36 cycles; 6 crew events','Completed; checks passed'],['IMG_9674 / 21 seconds<br/>(final crop-boundary fix)','8 rowers; 54 cycles; 9 crew events','Completed; checks passed']],y,[180,204,132])
y=p('Saved-output checks cover timing arithmetic, observation counts, unique crew-event use and evidence integrity. Counts and estimated rates are diagnostics, not accuracy labels. The 9673 run preceded the final crop fix; the 9674 run included it. [8]',y,style='small')-23
y=h('Experiments not adopted',y)
y=table([['Experiment','Why it stayed out of production'],['Larger pose backbones','No convincing localization win in the small audit; medium inference cost was about 5x the nano model in the controlled CPU comparison.'],['Tighter person crops','Mixed joint-placement results; no consistent improvement.'],['Neighbor-frame optical flow<br/>and mirrored inference','No convincing aggregate gain; some wrist estimates worsened.'],['Every source frame / wider smoothing','Full-rate processing cost more without established real-video accuracy gain. Wider filtering reduced random noise but blurred clean motion and barely helped persistent errors.']],y,[185,331])
p('These decisions preserve useful detail and avoid adding complexity or inference cost on the strength of smoother-looking output alone. The original nano model remains the default. [3, 9]',y,style='small')
end()

# 6
y=page(6,'Handoff and evidence','What is stronger - and what remains','The work is paused. This report summarizes the saved implementation and evidence; it does not claim the model is finished or independently validated.')
y=h('Remaining precision limits',y)
y=p('Wrist and hip localization can still be wrong despite high detector confidence. Some finishes span several similar poses, so an exact timestamp is not visually resolvable. Angles are projected 2D measurements and remain sensitive to viewpoint, overlap and hidden anatomy. The new crop rule has targeted regression evidence, not broad held-out validation.',y)-18
y=h('Recommended next work when resumed',y)
y=p('1. Build an independently labeled rowing benchmark covering clear side-on motion, different stroke rates, body types and cameras.<br/>2. Expand crop-boundary and phase-selection comparisons on footage not used to tune the changes.<br/>3. Use those labels to guide pose-model refinement or fine-tuning, with joint-position and event-time error as the acceptance criteria.',y)-21
y=h('Evidence ledger',y)
y=p('Paths below are relative to <b>app/strokesense/</b> in the local workspace. Frozen baselines, replay scripts and detailed caveats are retained alongside the results.',y,style='small')-10
sources=[
 ('[1] Tracking','evaluation/tracking/results.json; README.md'),
 ('[2] Crop correction','evaluation/body_motion/README.md; crop_edge_compare.py'),
 ('[3] Body-motion tests','evaluation/body_motion/synthetic-comparison.json'),
 ('[4] Fractional timing','evaluation/stroke_timing/README.md; results.json'),
 ('[5] Event source review','evaluation/events/README.md; comparison.json'),
 ('[6] Rhythm and crew timing','evaluation/rhythm/README.md; evaluation/synchrony/README.md'),
 ('[7] Final regression log','results/body-motion-evaluation/crop-edge-comparison/full-tests.log'),
 ('[8] Fresh pipeline checks','evaluation/pipeline/results.json; results/crop-edge-pipeline/verification.json'),
 ('[9] Sampling experiments','evaluation/sampling/README.md; filter_support_results.json')]
# Compact source ledger with wrapped, readable paths.
for label,path in sources:
 y=p(f'<b>{label}</b> - {path}',y,style='small')-7
y=note('<b>Scope preserved.</b> No UI or offering changes, no neural-weight retraining and no footage upload as part of this work. Existing workspace changes were preserved. The full work record is evaluation/ACCURACY_WORK_LOG.md.',y-3)
end();c.save()
reader=PdfReader(str(OUT));assert len(reader.pages)==6
for i,page in enumerate(reader.pages):
 text=page.extract_text();assert len(text)>500,(i,len(text))
print(OUT);print('pages',len(reader.pages),'bytes',OUT.stat().st_size)
