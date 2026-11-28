// Short explanations shown on hover or keyboard focus.
export const HELP = {
  hook: 'The opening scene, the first seconds of the ad. Its only job is to stop people scrolling.',
  demo: 'A middle scene: the product in use, showing what it does and why it matters.',
  cta: 'The last scene, the call to action: what to do next, with your offer. The end card with the button follows it.',
  pov: 'Point of view: puts the viewer in the moment, for example "POV: you finally found…".',
  problem_first: 'Opens with a problem the viewer knows, then shows the product as the fix.',
  three_reasons: 'A quick list ("3 reasons…"): promises value in a few seconds.',
  unboxing_tease: 'Builds curiosity by revealing the product step by step.',
  description: 'What happens in this scene, in plain words (with your own story: your text for this scene). The AI gets two instructions written from it: a starting picture and the movement; open "Show what the AI gets" to see or change them.',
  voiceover:
    'The line the AI voice says in this scene (about 12 words, about 4 seconds), also shown as captions. Empty means nothing is said: type your own line or pick one of the AI\'s suggestions. Lines your story gives as spoken words are filled in for you.',
  on_screen_text:
    'A short headline burned onto the top of the video during this scene. Empty means no text: type your own or pick one of the AI\'s suggestions.',
  image_prompt:
    'Exact instructions for the image model: subject, setting, framing, camera and lens, light, colours and style.',
  motion_prompt:
    'Shot list for the video model: what happens second by second, how the camera moves, and the final frame. More detail gives a better clip.',
  clip: 'How long this scene is on screen: 2 to 10 seconds. The video AI only makes 5 s or 10 s clips and is paid for the whole clip; for a shorter scene we use the first seconds of it.',
  ad_length: 'How long the whole finished video is, including the 2-second end card with your offer and button. It is split evenly over the scenes (each 2 to 10 s); you can still set each scene in Scenes.',
  scenes: 'Each scene: what we see, the spoken line, the headline, where its image comes from, its length and the prompts. Open it only if you want to check or change something.',
  make: 'Images first: you check the pictures and can still edit before paying for video. Video: images and video in one go, for when everything is ready.',
  image_source:
    'Generate a new picture from your product photo, use your product photo as it is, or upload a picture you already have (free). A picture much wider or squarer than the ad is extended by the AI to fill the frame, for one picture\'s price.',
  story:
    'AI storyboard: written from your brief. My own story: paste your story or script (up to 12,000 characters); your spoken lines are kept word for word and the scenes, prompts and hooks follow it.',
  hooks: 'Optional. The opening line decides if people keep watching. Keep yours, pick one of three ideas, or write your own; it replaces scene 1\'s first line.',
  title: 'A name for this ad, for you and for the file names.',
  cta_text: 'The words on the button in the end card.',
  visual_style:
    'How every picture and clip looks. Realistic and cinematic keep your real product most faithfully; 3D and 2D restyle the whole scene.',
  goal: 'What the ad should achieve. It steers the script: sales pushes the offer, awareness the name, visits the link.',
  theme:
    "Fills what you did not set: settings, props, pace, tone of voice, caption style, colours, font, the end card's look and the music track. Your story and your brand kit always win. With no story, the AI also gets the theme's scene and hook ideas.",
  ad_type: 'The format of the story. Testimonial uses only quotes and claims you write yourself.',
  voice: 'The AI voice that reads the voiceover. Viewers must be told it is AI: turn on the AI label when you post.',
  continuity: 'Each shot also has its own switch: "Flows on" or "Cut to a new picture". One connected video: every scene flows into the next with no jump. A scene set to "Continue" starts from the last frame of the one before; a scene with your own picture is reached by the clip before it, which ends on that picture. Separate shots: each scene starts from its own picture, with a soft blend at each cut (best for different places or angles).',
  flow: 'Written for you after the story is read, so each cut matches: how this scene starts and ends (camera position, direction and speed, pose, light), and what stays the same in every scene. Only the AI gets it; your story text is not changed. You can edit it.',
  notes: 'Optional. Things true for the whole ad (look, place, weather, light, colours, camera rules). When your story has them before the timed parts, they are put here for you. They are added to every scene, so all scenes match.',
  video_length: 'How long the finished video should be. The app turns it into scenes of about 2.5 s each (more scenes give more detail). Auto follows your story. If your story has timestamps, they decide.',
  ratio: 'The shape of the video. Choosing the platform picks its best shape for you: 9:16 (full-screen vertical) for TikTok, Reels and Shorts, 4:5 for the Facebook feed. You can still change it.',
  music: 'A licensed background track for the theme, lowered while the voice speaks.',
  captions: 'The voiceover as burned-in text, for people watching with the sound off.',
  sound: 'The voice, music and captions of the whole ad. Press the list icon to listen before you choose. You can change them until the video is made.',
  add_scene: 'Add a scene or shot (up to 20). Each shot is one picture and one clip.',
  cutting:
    'Your story decides how many cuts there are: write "cut to", "quick cuts of A, B and C", scene headings or timestamps, and each cut becomes its own shot (up to 20). This choice says how the shots meet. Auto: a shot flows on from the one before, and cuts where your story says so or where the person or place changes. One flowing take: as few cuts as possible. Many quick cuts: a clean cut at every shot. Separate shots: each from its own picture with a soft blend. Each shot costs one clip (about 0.32 EUR), so the price is shown before anything is made.',
  join:
    'Flows on: this shot starts from the last frame of the one before, so there is no jump. Cut to a new picture: a clean cut to a picture of its own, for a new person, place or angle (one picture\'s price).',
  end_card:
    'Your story ends on a logo or brand on screen, so we make it as the end card: your product name, offer and button on a plain background, with the spoken line. The video AI writes letters and logos badly, so this is sharper and free.',
  cast_world:
    'Who and what is in your ad, the same in every scene: the product, the people, the place, the light, the look and what never to show. Taken from your words where you gave them ("yours") and guessed by the AI where you did not ("AI\'s guess"). The scenes below were written with it, and every clip is built from it: press Edit to change an entry, and it becomes yours in every scene.',
  guesses:
    'What the AI used for this scene. "Yours" comes from your words; "AI\'s guess" fills a gap you left. Press Edit to change one: what you type becomes yours and goes into this scene\'s clip.',
  length_line:
    'Your scenes are never slowed down or held still to fill time, because that looks worse. Add scenes that fit your story, or keep the length your scenes make.',
  approve_images: 'Step 1 makes one picture per scene. You see them before any video is paid for.',
  make_video: 'Step 2: voiceover, one clip per scene, captions, music and the end card, in every format.',
};
