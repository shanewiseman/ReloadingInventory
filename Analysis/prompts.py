DETECTION_INSTRUCTIONS = """
You analyze range paper target photos for marksmanship statistics.
Return only structured data that matches the supplied schema.

Coordinate rules:
- The target center/bullseye is x=0, y=0.
- x_inches is positive to the shooter's right.
- y_inches is positive upward.
- The reference image shows the desired output coordinate system: 1 inch ring spacing,
  a red center circle with a 1 inch diameter, and a 6 inch usable radius.
- Assume one shot group per submitted photo.
- If the target has visible 1 inch grids or 1 inch rings, use them for scale.
- If the target center or scale is uncertain, still return your best estimate and lower confidence.
- Return bullet-hole centers, not torn-paper outer edges.
""".strip()


VERIFICATION_INSTRUCTIONS = """
You review a rendered target image and the raw detection coordinates from a range target analysis.
Return only structured data that matches the supplied schema.

Do not recompute MOA. The application computes final statistics deterministically.
Focus on whether the rendered shot placement appears consistent with the supplied coordinates,
whether any bullet hole looks suspicious, and whether the confidence should be lowered.
""".strip()


def detection_prompt(description, distance_value, distance_unit, width, height):
    return f"""
Analyze the submitted range target photo.

Shooting context:
{description or "No additional context provided."}

Submitted distance: {distance_value} {distance_unit}
Normalized image dimensions: {width} x {height} pixels

Return shot center coordinates in both image pixels and inches from the target center.
Shots beyond a 6 inch radius may be returned, but the application will exclude them from group statistics.
""".strip()


def verification_prompt(job, preliminary_group):
    return f"""
Review this rendered target image and raw shot data for a single group.

Distance:
{job["distance"]}

Raw shots:
{job["shots"]}

Excluded shots:
{job["excluded_shots"]}

Preliminary computed group:
{preliminary_group}

Return warnings for low-confidence detections or coordinate inconsistencies.
""".strip()
