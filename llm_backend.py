#!/usr/bin/env python3
"""
LLM Backend - lokaal taalmodel via llama-cpp-python met GGUF quantized models.
Thinking + tool calling voor photo/video/audio generatie.
"""
import gc
import json
import os
import re
import sys
from pathlib import Path

_llm = None
_model_name = None
_MAX_HISTORY = 20

MODEL_DIR = Path("models/llm")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

THINK_TAG_OPEN = "<thinking>"
THINK_TAG_CLOSE = "</thinking>"

SYSTEM_PROMPT = """Je bent een lokale AI assistent op de Mac van de gebruiker.

Tools (alleen gebruiken wanneer gevraagd):
MEDIA: generate_photo (prompt), generate_video (prompt), generate_audio (prompt)
HULP: internet_search (query), execute_code (code), file_read (path), file_write (path, content), file_list (directory), run_command (command), web_fetch (url)
SYSTEEM: get_system_info (), get_model_status (), gallery_list (gallery_type)

Structuur: denk tussen <thinking></thinking>, dan tool call OF antwoord.
Vertel ALTIJD kort wat je gaat doen voordat je een tool gebruikt. Bijvoorbeeld:
- "Ik ga een foto genereren van een grijze kat op zee..."
- "Ik zoek dit even voor je op..."
- "Ik controleer welke modellen er geinstalleerd zijn..."
Tool formaat: [TOOL:naam][PARAM:key]value[/PARAM][/TOOL]
Regels: dezelfde taal als gebruiker, geen server vermelden, bij twijfel geen tool."""

MODEL_OPTIONS = {
    "small": {
        "repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "file": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    },
    "medium": {
        "repo": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "file": "qwen2.5-3b-instruct-q4_k_m.gguf",
    },
    "large": {
        "repo": "bartowski/Phi-3.5-mini-instruct-GGUF",
        "file": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
    },
}

TOOL_DEFAULTS = {
    "generate_photo": {"width": 512, "height": 512, "num_inference_steps": 30, "guidance_scale": 10.0, "model": "sd15"},
    "generate_video": {"num_frames": 8, "width": 384, "height": 384, "num_inference_steps": 4, "guidance_scale": 2.0, "fps": 8},
    "generate_audio": {"duration_seconds": 30, "guidance_scale": 7.0},
    "internet_search": {"max_results": 5},
    "execute_code": {},
    "file_read": {"max_lines": 500},
    "file_write": {},
    "file_list": {},
    "run_command": {"timeout": 15},
    "get_system_info": {},
    "get_model_status": {},
    "web_fetch": {"max_chars": 5000},
    "gallery_list": {"gallery_type": "photos"},
}


def _ensure_model(model_size="small", progress_callback=None):
    from huggingface_hub import hf_hub_download

    info = MODEL_OPTIONS.get(model_size, MODEL_OPTIONS["small"])
    model_path = MODEL_DIR / info["file"]

    if not model_path.exists():
        if progress_callback:
            progress_callback(15, f"Model downloaden ({info['file']})... Dit kan even duren.")
        print(f"[LLM] Model downloaden: {info['repo']}...")
        path = hf_hub_download(
            repo_id=info["repo"],
            filename=info["file"],
            local_dir=str(MODEL_DIR),
        )
        model_path = Path(path)
        if progress_callback:
            progress_callback(25, "Download voltooid! Model laden...")

    return str(model_path)


def load_model(model_size="small", progress_callback=None):
    global _llm, _model_name

    if _llm is not None and _model_name == model_size:
        return _llm

    from llama_cpp import Llama

    if progress_callback:
        progress_callback(10, "Model controleren...")

    model_path = _ensure_model(model_size, progress_callback)

    if progress_callback:
        progress_callback(30, "Model laden in geheugen...")

    print(f"[LLM] Laden: {model_path}")
    _llm = Llama(
        model_path=model_path,
        n_ctx=4096,
        n_threads=os.cpu_count() or 4,
        n_batch=512,
        verbose=False,
    )
    _model_name = model_size

    if progress_callback:
        progress_callback(100, "Model geladen!")

    print("[LLM] Model geladen!")
    return _llm


def _format_messages(messages):
    formatted = [{"role": "system", "content": SYSTEM_PROMPT}]
    recent = messages[-_MAX_HISTORY:] if len(messages) > _MAX_HISTORY else messages
    for msg in recent:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant", "system"):
            formatted.append({"role": role, "content": content})
    return formatted


def _parse_response(text):
    thinking = ""
    tool_call = None
    response = text

    think_match = re.search(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        after = text[think_match.end():].strip()
    else:
        after = text

    tool_match = re.search(
        r"\[TOOL:(\w+)\](.*?)(?:\[/TOOL\]|$)",
        after, re.DOTALL
    )
    if tool_match:
        func_name = tool_match.group(1)
        params_block = tool_match.group(2)

        args = {}
        for p in re.finditer(r"\[PARAM:(\w+)\](.*?)\[/PARAM\]", params_block, re.DOTALL):
            val = p.group(2).strip().strip('"').strip("'")
            if val.isdigit():
                args[p.group(1)] = int(val)
            else:
                try:
                    args[p.group(1)] = float(val)
                except ValueError:
                    args[p.group(1)] = val

        if func_name in TOOL_DEFAULTS:
            defaults = TOOL_DEFAULTS[func_name].copy()
            defaults.update(args)
            tool_call = {"name": func_name, "args": defaults}

        text_before_tool = after[:tool_match.start()].strip()
        response = text_before_tool if text_before_tool else ""
    else:
        response = after

    return thinking, tool_call, response


def chat_completion(messages, model_size="small", max_tokens=1024,
                    temperature=0.7, top_p=0.9, progress_callback=None):
    llm = load_model(model_size, progress_callback)

    if progress_callback:
        progress_callback(80, "Antwoord genereren...")

    formatted = _format_messages(messages)

    output = llm.create_chat_completion(
        messages=formatted,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        repeat_penalty=1.1,
        frequency_penalty=0.1,
    )

    gc.collect()

    choice = output["choices"][0]
    content = choice["message"]["content"]
    usage = output.get("usage", {})
    thinking, tool_call, response = _parse_response(content)

    return {
        "thinking": thinking,
        "content": response,
        "tool_call": tool_call,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }


def chat_completion_with_tools(messages, model_size="small", max_tokens=1024,
                                temperature=0.7, top_p=0.9,
                                tool_executor=None, progress_callback=None,
                                token_callback=None):
    llm = load_model(model_size, progress_callback)
    formatted = _format_messages(messages)
    all_tool_results = []
    total_prompt = 0
    total_completion = 0
    all_thinking = []

    for iteration in range(5):
        if progress_callback:
            if iteration == 0:
                progress_callback(70, "Nadenken...")
            else:
                progress_callback(80, "Verwerken...")

        if token_callback:
            full_content = ""
            stream = llm.create_chat_completion(
                messages=formatted,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                repeat_penalty=1.1,
                frequency_penalty=0.1,
                stream=True,
            )
            for chunk in stream:
                delta = chunk["choices"][0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    full_content += token
                    token_callback(token)
            content = full_content
        else:
            output = llm.create_chat_completion(
                messages=formatted,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                repeat_penalty=1.1,
                frequency_penalty=0.1,
            )
            choice = output["choices"][0]
            content = choice["message"].get("content", "")
            usage = output.get("usage", {})
            total_prompt += usage.get("prompt_tokens", 0)
            total_completion += usage.get("completion_tokens", 0)

        thinking, tool_call, response = _parse_response(content)

        if thinking:
            all_thinking.append(thinking)
            if progress_callback:
                progress_callback(75, f"Denkt na: {thinking[:80]}...")

        if response and progress_callback:
            progress_callback(80, response)

        if not tool_call:
            gc.collect()
            final_content = response if response else ""
            return {
                "thinking": "\n\n".join(all_thinking),
                "content": final_content,
                "tool_results": all_tool_results,
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
            }

        func_name = tool_call["name"]
        args = tool_call["args"]

        print(f"[LLM] Thinking: {thinking[:120]}...")
        print(f"[LLM] Tool call: {func_name}({args})")

        if progress_callback:
            progress_callback(78, f"Tool: {func_name}...")

        if tool_executor:
            result = tool_executor(func_name, args)
        else:
            result = {"error": "Geen tool executor beschikbaar"}

        result_str = json.dumps(result, ensure_ascii=False)
        all_tool_results.append(result)

        formatted.append({"role": "assistant", "content": content})
        formatted.append({
            "role": "user",
            "content": f"Tool-resultaat: {result_str}\n\nAntwoord kort in dezelfde taal. Geen thinking tags of tools."
        })

    gc.collect()
    return {
        "thinking": "\n\n".join(all_thinking),
        "content": "Het genereren is voltooid.",
        "tool_results": all_tool_results,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
    }


def unload_model():
    global _llm, _model_name
    _llm = None
    _model_name = None
    gc.collect()
    print("[LLM] Model uit geheugen gelost")
