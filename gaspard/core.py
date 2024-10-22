# AUTOGENERATED! DO NOT EDIT! File to edit: ../00_core.ipynb.

# %% auto 0
__all__ = ['UsageMetadata', 'empty', 'models', 'j2p_map', 'find_block', 'contents', 'usage', 'mk_msgs', 'Client', 'get_stream',
           'convert_func', 'mk_toolres', 'json2proto', 'cls2tool', 'mk_args', 'mk_tool_config', 'Chat', 'media_msg',
           'text_msg', 'mk_msg']

# %% ../00_core.ipynb
import inspect, typing, mimetypes, base64, json, ast, os, time, proto
import google.generativeai as genai
from google.generativeai.types.generation_types import GenerateContentResponse, GenerationConfig
from google.generativeai.protos import FunctionCall, Content, FunctionResponse, FunctionDeclaration
from google.generativeai.protos import GenerateContentResponse as GCR
from google.generativeai import protos

import toolslm
from toolslm.funccall import *

from fastcore.meta import delegates
from fastcore.utils import *

from collections import abc

from proto.marshal.collections.maps import MapComposite
from proto.marshal.collections.repeated import RepeatedComposite

# %% ../00_core.ipynb
UsageMetadata = GCR.UsageMetadata
empty = inspect.Parameter.empty

# %% ../00_core.ipynb
models = 'gemini-1.5-pro-exp-0827', 'gemini-1.5-flash-exp-0827','gemini-1.5-pro','gemini-1.5-flash'

# %% ../00_core.ipynb
def find_block(r:abc.Mapping, # The message to look in
              ):
    "Find the content in `r`."
    m = nested_idx(r, 'candidates', 0)
    if not m: return m
    if hasattr(m, 'content'): return m.content 
    else: return m

# %% ../00_core.ipynb
def contents(r):
    "Helper to get the contents from response `r`."
    blk = find_block(r)
    if not blk: return r
    if hasattr(blk, 'parts'): return getattr(blk,'parts')[0].text
    return blk

# %% ../00_core.ipynb
@patch()
def _repr_markdown_(self:GenerateContentResponse):
    met = list(self.to_dict()['candidates'][0].items()) + list(self.to_dict()['usage_metadata'].items())
    det = '\n- '.join(f'{k}: {v}' for k,v in met)
    res = contents(self)
    if not res: return f"- {det}"
    return f"""{contents(self)}\n<details>\n\n- {det}\n\n</details>"""

# %% ../00_core.ipynb
def usage(inp=0, # Number of input tokens
          out=0  # Number of output tokens
         ):
    "Slightly more concise version of `Usage`."
    return UsageMetadata(prompt_token_count=inp, candidates_token_count=out)

# %% ../00_core.ipynb
@patch(as_prop=True)
def total(self:UsageMetadata): return self.prompt_token_count+self.candidates_token_count

# %% ../00_core.ipynb
@patch
def __repr__(self:UsageMetadata): return f'In: {self.prompt_token_count}; Out: {self.candidates_token_count}; Total: {self.total}'

# %% ../00_core.ipynb
@patch
def __add__(self:UsageMetadata, b):
    "Add together each of `input_tokens` and `output_tokens`"
    return usage(self.prompt_token_count+b.prompt_token_count, self.candidates_token_count+b.candidates_token_count)

# %% ../00_core.ipynb
def mk_msgs(msgs:list, **kw):
    "Helper to set 'assistant' role on alternate messages."
    if isinstance(msgs,str): msgs=[msgs]
    return [mk_msg(o, ('user','model')[i%2], **kw) for i,o in enumerate(msgs)]

# %% ../00_core.ipynb
class Client:
    def __init__(self, model, cli=None, sp=None):
        "Basic LLM messages client."
        self.model,self.use = model,usage(0,0)
        self.sp = sp
        self.c = (cli or genai.GenerativeModel(model, system_instruction=sp))

# %% ../00_core.ipynb
@patch
def _r(self:Client, r:GenerateContentResponse):
    "Store the result of the message and accrue total usage."
    self.result = r
    if getattr(r,'usage_metadata',None): self.use += r.usage_metadata
    return r

# %% ../00_core.ipynb
def get_stream(r):
    for o in r:
        o = contents(o)
        if o and isinstance(o, str): yield(o)

# %% ../00_core.ipynb
@patch
def _set_sp(self:Client, sp:str):
    if sp != self.sp:
        self.sp = sp
        self.c = genai.GenerativeModel(model, system_instruction=self.sp)

# %% ../00_core.ipynb
@patch
def _precall(self:Client, msgs):
    if not isinstance(msgs,list): msgs = [msgs]
    msgs = mk_msgs(msgs)
    return msgs

# %% ../00_core.ipynb
@patch
@delegates(genai.GenerativeModel.generate_content)
def __call__(self:Client,
             msgs:list, # List of messages in the dialog
             sp:str=None, # System prompt
             maxtok=4096, # Maximum tokens
             stream:bool=False, # Stream response?
             **kwargs):
    "Make a call to LLM."
    if sp: self._set_sp(sp)
    msgs = self._precall(msgs)
    gc_params = inspect.signature(GenerationConfig.__init__).parameters
    gc_kwargs = {k: v for k, v in kwargs.items() if k in gc_params}
    gen_config = GenerationConfig(max_output_tokens=maxtok, **gc_kwargs)
    gen_params = inspect.signature(self.c.generate_content).parameters
    gen_kwargs = {k: v for k, v in kwargs.items() if k in gen_params}
    r = self.c.generate_content(
        contents=msgs, generation_config=gen_config, stream=stream, **gen_kwargs)
    if not stream: return self._r(r)
    else: return get_stream(map(self._r, r))

# %% ../00_core.ipynb
def contents(r):
    "Helper to get the contents from response `r`."
    blk = find_block(r)
    if not blk: return r
    
    if hasattr(blk, 'parts'):
        part = blk.parts[0]
        if 'text' in part:
            return part.text
        else:
            return part
    return blk

# %% ../00_core.ipynb
def convert_func(f): return AttrDict(name=f.name, inputs=mk_args(f.args))

# %% ../00_core.ipynb
def mk_toolres(
    r:abc.Mapping, # Tool use request response
    ns, # Namespace to search for tools
    ):
    "Create a `tool_result` message from response `r`."
    parts = find_block(r).parts
    tcs = [p.function_call for p in parts if hasattr(p, 'function_call')]
    res = [mk_msg(r)]
    tc_res = []
    for func in (tcs or []):
        if not func: continue
        func = convert_func(func)
        cts = call_func(func.name, func.inputs, ns=ns)
        tc_res.append(FunctionResponse(name=func.name, response={'result': cts}))
    if tc_res: res.append(mk_msg(tc_res))
    return res

# %% ../00_core.ipynb
def mk_msgs(msgs:list, **kw):
    "Helper to set 'assistant' role on alternate messages."
    if isinstance(msgs,str): msgs=[msgs]
    return [mk_msg(o, ('user','model')[i%2], **kw) for i,o in enumerate(msgs)]

# %% ../00_core.ipynb
j2p_map = {
    'string': protos.Type.STRING,
    'array': protos.Type.ARRAY,
    'object': protos.Type.OBJECT,
    'integer': protos.Type.INTEGER,
    'number': protos.Type.NUMBER,
    'boolean': protos.Type.BOOLEAN
}

# %% ../00_core.ipynb
def json2proto(schema_dict):
    "Convert JSON schema to protobuf schema"
    def _convert_type(t):
        return {'string': protos.Type.STRING, 'array': protos.Type.ARRAY, 'object': protos.Type.OBJECT}.get(t, protos.Type.TYPE_UNSPECIFIED)
    
    def _convert_property(prop, depth=0):
        schema = protos.Schema(type=j2p_map.get(prop.get('type'), protos.Type.TYPE_UNSPECIFIED))
        if 'items' in prop:
            ref = prop['items'].get('$ref')
            schema.items = _convert_property(schema_dict['input_schema']['$defs'][ref.split('/')[-1]], depth+1) if ref else _convert_property(prop['items'], depth+1)
        if 'properties' in prop: schema.properties = {k: _convert_property(v, depth+1) for k,v in prop['properties'].items()}
        if 'required' in prop: schema.required.extend(prop['required'])
        return schema
    
    return _convert_property(schema_dict['input_schema'])

# %% ../00_core.ipynb
def cls2tool(c) -> genai.protos.FunctionDeclaration:
    json_schema = get_schema(c)
    schema = json2proto(json_schema)
    return genai.protos.FunctionDeclaration(
        name=json_schema['name'],
        description=json_schema['description'],
        parameters=schema
    )

# %% ../00_core.ipynb
def _convert_proto(o):
    "Convert proto objects to Python dicts and lists"
    if isinstance(o, (dict,MapComposite)): return {k:_convert_proto(v) for k,v in o.items()}
    elif isinstance(o, (list,RepeatedComposite)): return [_convert_proto(v) for v in o]
    elif hasattr(o, 'DESCRIPTOR'): return {k.name:_convert_proto(getattr(o,k.name)) for k in o.DESCRIPTOR.fields}
    return o

# %% ../00_core.ipynb
def mk_args(args):
    if isinstance(args, MapComposite): return _convert_proto(args)
    return {k: v for k,v in args.items()}

# %% ../00_core.ipynb
def mk_tool_config(choose: list)->dict:
    return {"function_calling_config": {"mode": "ANY", "allowed_function_names":
    [x.__name__ if hasattr(x, '__name__') else x.name for x in choose]}}

# %% ../00_core.ipynb
@patch
@delegates(Client.__call__)
def structured(self:Client,
               msgs:list, # The prompt or list of prompts
               tools:list, # Namespace to search for tools
               **kwargs):
    "Return the value of all tool calls (generally used for structured outputs)"
    if not isinstance(msgs, list): msgs = [msgs]
    kwargs['tools'] = [cls2tool(x) for x in tools]
    kwargs['tool_config'] = mk_tool_config(kwargs['tools'])
    res = self(msgs, **kwargs)
    ns=mk_ns(*tools)
    parts = find_block(res).parts
    funcs = [convert_func(p.function_call) for p in parts if hasattr(p, 'function_call')]
    tcs = [call_func(func.name, func.inputs, ns=ns) for func in funcs]
    return tcs

# %% ../00_core.ipynb
class Chat:
    def __init__(self,
                 model:Optional[str]=None, # Model to use (leave empty if passing `cli`)
                 cli:Optional[Client]=None, # Client to use (leave empty if passing `model`)
                 sp=None, # Optional system prompt
                 tools:Optional[list]=None,  # List of tools to make available
                 tool_config:Optional[str]=None): # Forced tool choice
        "Gemini chat client."
        assert model or cli
        self.c = (cli or Client(model, sp=sp))
        self.h,self.sp,self.tools,self.tool_config = [],sp,tools,tool_config
    
    @property
    def use(self): return self.c.use

# %% ../00_core.ipynb
@patch
def _stream(self:Chat, res):
    yield from res
    self.h += mk_toolres(self.c.result, ns=self.tools)

# %% ../00_core.ipynb
@patch
def _post_pr(self:Chat, pr, prev_role):
    if pr is None and prev_role == 'assistant':
        raise ValueError("Prompt must be given after assistant completion, or use `self.cont_pr`.")
    if pr: self.h.append(mk_msg(pr))

# %% ../00_core.ipynb
@patch
def _append_pr(self:Chat,
               pr=None,  # Prompt / message
              ):
    prev_role = nested_idx(self.h, -1, 'role') if self.h else 'assistant' # First message should be 'user'
    if pr and prev_role == 'user': self() # already user request pending
    self._post_pr(pr, prev_role)

# %% ../00_core.ipynb
@patch
@delegates(genai.GenerativeModel.generate_content)
def __call__(self:Chat,
             pr=None,  # Prompt / message
             temp=0, # Temperature
             maxtok=4096, # Maximum tokens
             stream=False, # Stream response?
             **kwargs):
    if isinstance(pr,str): pr = pr.strip()
    self._append_pr(pr)
    if self.tools: kwargs['tools'] = self.tools
    # NOTE: Gemini specifies tool_choice via tool_config
    if self.tool_config: kwargs['tool_config'] = mk_tool_config(self.tool_config)
    res = self.c(self.h, stream=stream, sp=self.sp, temp=temp, maxtok=maxtok, **kwargs)
    if stream: return self._stream(res)
    self.h += mk_toolres(self.c.result, ns=self.tools)
    return res

# %% ../00_core.ipynb
def media_msg(fn: Path)->dict:
    if isinstance(fn, dict): return fn # Already processed
    f = genai.upload_file(fn)
    return {'file_data': {'mime_type': f.mime_type, 'file_uri': f.uri}}

# %% ../00_core.ipynb
def text_msg(s:str)->dict:
    return {'text': s}

# %% ../00_core.ipynb
def _mk_content(src):
    "Create appropriate content data structure based on type of content"
    if isinstance(src,str): return text_msg(src)
    if isinstance(src,FunctionResponse): return src
    else: return media_msg(src)

# %% ../00_core.ipynb
def mk_msg(content, role='user', **kw):
    if isinstance(content, GenerateContentResponse): role,content = 'model',contents(content)
    if isinstance(content, dict): role,content = content['role'],content['parts']
    if not isinstance(content, list): content=[content]
    if role == 'user': content = [_mk_content(o) for o in content] if content else ''
    return dict(role=role, parts=content, **kw)

# %% ../00_core.ipynb
def mk_msgs(msgs:list, **kw):
    "Helper to set 'assistant' role on alternate messages."
    if isinstance(msgs,str): msgs=[msgs]
    return [mk_msg(o, ('user','model')[i%2], **kw) for i,o in enumerate(msgs)]

# %% ../00_core.ipynb
def media_msg(fn: Path)->dict:
    if isinstance(fn, dict): return fn # Already processed
    print(f"Uploading media...", end='')
    f = genai.upload_file(fn)
    while f.state.name == "PROCESSING":
        print('.', end='')
        time.sleep(2)
        f = genai.get_file(f.name)
    return {'file_data': {'mime_type': f.mime_type, 'file_uri': f.uri}}
