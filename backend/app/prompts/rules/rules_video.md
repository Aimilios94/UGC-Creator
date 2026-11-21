# Video rules (image-to-video clips, Kling)

Each scene is one clip of 5 or 10 seconds, made from a first picture. The scenes play as one
ad, so each clip must join the next with no visible jump.

## One continuous take per clip
- A clip has no cuts. Never write "cut to" inside a scene.
- A "cut to" in the user's prompt starts a new scene when there is room (at most 5 scenes);
  otherwise it becomes a bridging movement between two scenes (a whip pan, a match on the same
  action, the camera pushing into a dark surface and out of one in the new place).
- Angle changes inside one take are written as camera moves, for example: "0-2 s: full-body shot,
  he walks in light rain. 2-4 s: the camera pushes in to his footsteps. 4-5 s: it pulls back to a
  medium shot as he stops."

## Action, camera and timeline
- One main action per clip, in plain verbs: "walks toward the camera, stops, lifts the mug to her
  face".
- Camera words: static, slow push in, pull back, pan, tilt, orbit, crane up, tracking, handheld.
  Give the speed (slow, steady, fast) and the shot size (close-up, medium, wide).
- Timeline: 2 to 4 time marks for a 5 s clip, up to 5 for a 10 s clip, in seconds from the
  start of the clip ("0-2 s: ... 2-4 s: ...").
- Lengths come from the length planner: 5 s first; 10 s when the action needs it or the user
  asked for it.

## Start and end frames
- start: the first moment of the shot: camera position (distance, height, angle), the move
  already under way (direction and speed), the subject's pose and gaze, the light.
- end: the last moment, described the same way. For the last scene, how the ad ends.
- At every cut, scene N's end and scene N+1's start describe the same moment, in the same words
  where possible. A move in progress carries on through the cut; it never stops and restarts.
- The next clip starts from the previous clip's last frame, or the clip ends on the next
  scene's own picture.

## Anchors
Keep the same in every clip: the product (shape, colours, logo, printed text), each person's
face, hair and clothes, details on the hidden side (a back print), the place, the light and the
lens. Describe only the cast in the shot.

## Kling weak spots: swap the action, keep the intent
| Kling is bad at | Write instead |
| --- | --- |
| Crowds doing complex actions | The crowd still or staring; the action on the main subject |
| Throws, catches, pouring, liquids | Before and after, or start the clip after the moment (the cup is already full, steam rising) |
| Hands handling small parts | A simple hold or a slow turn of the product |
| Things changing shape | Two scenes: closed in one, open in the next |
| Text, logos, screens with words | A blank screen glow; words are added later in editing |
| Fast spins and big jumps | A slow push in or a slow orbit |
| Several people interacting | One person, or a fixed place for each person ("P2 stays on the left, seated") |

## What not to write
- No written words, captions, signs or logos in the picture: on-screen text is added later.
- Negatives (what to avoid) go in the scene's avoid slot and the sheet's never slot, not in the
  action. They are sent in their own field.

## The clip budget
The video AI reads at most 2,500 characters per clip. Code builds each clip's text from the
slots with a fixed budget per part, so write short, exact phrases:
- movement (action, camera, timeline): up to 1,000 characters (up to 1,400 when other parts are short);
- who and the product: up to 400;
- start and end: up to 180 each;
- place, light and look: up to 250;
- fixed rules: 300, added by code.
Prefer exact visual facts (colours, materials, lens, light direction) over adjectives.

## No first picture
"No picture, text only" makes a clip from text alone. The look may change between scenes, so
it is only a fallback for one scene; a first picture is the default.
