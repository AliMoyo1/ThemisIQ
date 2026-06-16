"""
One For All - AI Control Generator.

Uses AI to generate compliance controls for frameworks that don't have
pre-defined seed data (e.g. custom frameworks created by the user).

Uses the unified core.ai_client for multi-provider support
(Anthropic, DeepSeek, Gemini, OpenAI, Ollama).
"""
import json
import logging
import re

from core.ai_client import create_message, is_configured, provider_name

log = logging.getLogger("oneforall.ai_controls")


def generate_controls_for_framework(
    framework_name: str,
    framework_description: str = "",
    relevant_modules: str = "",
    count_hint: int = 15,
) -> list[dict]:
    if not is_configured():
        raise RuntimeError(
            f"{provider_name()} API key not set. Configure it in your .env file."
        )

    system_prompt = (
        "You are a compliance and governance expert. Generate realistic, actionable "
        "compliance controls for the given framework. Each control should have a "
        "reference code, name, category, description, document type, and priority.\n\n"
        "Return ONLY a JSON array of objects with these exact keys:\n"
        '- "ref": control reference code (e.g. "CTRL-1", "A.5.1")\n'
        '- "name": short control name\n'
        '- "category": control category (e.g. "Organizational", "Technical", "Physical")\n'
        '- "description": one-sentence description of what the control requires\n'
        '- "doc_type": one of "Policy", "Procedure", "Standard", "Guideline"\n'
        '- "priority": one of "Critical", "High", "Medium", "Low"\n\n'
        "Do not include any text outside the JSON array. No markdown fences."
    )

    user_msg = (
        f"Generate {count_hint} compliance controls for the following framework:\n\n"
        f"Framework: {framework_name}\n"
    )
    if framework_description:
        user_msg += f"Description: {framework_description}\n"
    if relevant_modules:
        user_msg += f"Relevant modules: {relevant_modules}\n"
    user_msg += (
        "\nGenerate controls that are specific to this framework's domain. "
        "Use appropriate reference codes that match the framework's naming convention. "
        "Include a mix of organizational, technical, and procedural controls."
    )

    try:
        text = create_message(
            [{"role": "user", "content": user_msg}],
            system=system_prompt,
            max_tokens=4000,
        )
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()

        controls = json.loads(text)
        if not isinstance(controls, list):
            raise ValueError("AI response was not a JSON array")

        validated = []
        for ctrl in controls:
            if not isinstance(ctrl, dict):
                continue
            validated.append({
                "ref": str(ctrl.get("ref", "")).strip()[:20],
                "name": str(ctrl.get("name", "")).strip()[:200],
                "category": str(ctrl.get("category", "General")).strip()[:100],
                "description": str(ctrl.get("description", "")).strip()[:500],
                "doc_type": str(ctrl.get("doc_type", "Policy")).strip(),
                "priority": str(ctrl.get("priority", "High")).strip(),
            })

        log.info("AI generated %d controls for '%s'", len(validated), framework_name)
        return validated

    except json.JSONDecodeError as e:
        log.error("AI returned invalid JSON for '%s': %s", framework_name, e)
        raise RuntimeError("AI generated invalid response. Please try again.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"AI generation failed: {e}")
