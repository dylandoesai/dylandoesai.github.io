Penelope Cruz reference photos go here.

Required: 1+ JPG or PNG files of Penelope's face.
Recommended: 3-5 photos at different angles, averaged for best 3D depth.

  - 1 front-on (eyes level, looking at camera)
  - 1 three-quarter left   (head turned ~30° to her right)
  - 1 three-quarter right  (head turned ~30° to her left)
  - 1 slightly looking up    (helps chin/jaw)
  - 1 slightly looking down  (helps brow/forehead)

Specs:
  - 1024px+ on the long edge
  - Even lighting, no harsh shadows
  - Neutral expression, mouth closed (so lip geometry isn't stretched)
  - Face fills 40%+ of the frame
  - No filters / heavy retouching

After dropping the photos, run:
  python python/extract_face_mesh.py assets/reference/*.jpg

This writes assets/face-mesh.json, which the particle renderer loads at
startup. From then on, the particles literally form HER face geometry.

(Personal use only — extracted landmarks should not be redistributed.)
