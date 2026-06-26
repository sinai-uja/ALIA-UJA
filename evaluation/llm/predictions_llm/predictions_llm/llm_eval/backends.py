import abc
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, StoppingCriteria, StoppingCriteriaList


class LLMBackend(abc.ABC):
    """Interfaz común para backends de inferencia."""

    def __init__(self, model_path: str, **kwargs):
        self.model_path = model_path
        self.kwargs = kwargs
        self.tokenizer = None

    @abc.abstractmethod
    def load(self):
        """Carga el modelo y el tokenizer."""
        pass

    @abc.abstractmethod
    def generate(self, prompts: list[str]) -> list[str]:
        """Genera respuestas para una lista de prompts."""
        pass


class VLLMBackend(LLMBackend):
    """Backend basado en vLLM (alto throughput, multi-GPU)."""

    def load(self):
        from vllm import LLM, SamplingParams

        print(f"Cargando modelo con vLLM (bfloat16)...")
        self.llm = LLM(
            model=self.model_path,
            trust_remote_code=True,
            dtype="bfloat16",
            tensor_parallel_size=self.kwargs.get("tensor_parallel_size", 1),
        )
        self.tokenizer = self.llm.get_tokenizer()

        # Detectar token de parada adicional (<|im_end|>) si existe
        stop_token_ids = None
        try:
            im_end_id = self.tokenizer.convert_tokens_to_ids("<|im_end|>")
            if im_end_id is not None and im_end_id != self.tokenizer.unk_token_id:
                stop_token_ids = [im_end_id]
                print(f"Token extra de parada: '<|im_end|>' (id={im_end_id})")
        except Exception:
            pass

        self.sampling_params = SamplingParams(
            temperature=0.0,
            max_tokens=self.kwargs.get("max_new_tokens", 400),
            stop=self.kwargs.get("stop_sequences", []),
            stop_token_ids=stop_token_ids,
        )
        print("Modelo cargado.\n")

    def generate(self, prompts: list[str]) -> list[str]:
        outputs = self.llm.generate(prompts, self.sampling_params)
        return [out.outputs[0].text.strip() for out in outputs]


class StopOnSequences(StoppingCriteria):
    """Para la generación en cuanto aparece cualquiera de las stop_sequences."""

    def __init__(self, stop_sequences: list[str], tokenizer, prompt_len: int):
        self.stop_ids = []
        for seq in stop_sequences:
            ids = tokenizer.encode(seq, add_special_tokens=False)
            if ids:
                self.stop_ids.append(torch.tensor(ids))
        self.prompt_len = prompt_len

    def __call__(self, input_ids: torch.LongTensor, scores, **kwargs) -> bool:
        generated = input_ids[0, self.prompt_len:]
        for stop in self.stop_ids:
            n = len(stop)
            if len(generated) >= n and torch.equal(generated[-n:], stop.to(generated.device)):
                return True
        return False


class TransformersBackend(LLMBackend):
    """Backend basado en transformers (más flexible, 1 GPU)."""

    def load(self):
        print(f"Cargando tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)

        # Detección de Flash Attention 2
        try:
            import flash_attn  # noqa: F401
            major, _ = torch.cuda.get_device_capability()
            if major >= 8:
                attn_impl = "flash_attention_2"
                print("Flash Attention 2 disponible → usando flash_attention_2")
            else:
                attn_impl = "eager"
                print(f"GPU sm_{major}x no soporta Flash Attention 2 → usando eager attention")
        except ImportError:
            attn_impl = "eager"
            print("flash-attn no instalado → usando eager attention")

        print(f"Cargando modelo (bfloat16, device_map=auto, attn={attn_impl})...")
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            device_map="auto",
            torch_dtype=torch.bfloat16,
            trust_remote_code=True,
            attn_implementation=attn_impl,
        )
        self.model.eval()
        print(f"Modelo cargado.\n")

        # Token de parada dual: eos_token + <|im_end|>
        im_end_id = self.tokenizer.convert_tokens_to_ids("<|im_end|>")
        if im_end_id == self.tokenizer.unk_token_id or im_end_id is None:
            self.eos_ids = [self.tokenizer.eos_token_id]
            print(f"Token de parada: eos_token '{self.tokenizer.eos_token}' (id={self.tokenizer.eos_token_id})")
        else:
            self.eos_ids = [self.tokenizer.eos_token_id, im_end_id]
            print(f"Token de parada: eos='{self.tokenizer.eos_token}' (id={self.tokenizer.eos_token_id}) + '<|im_end|>' (id={im_end_id})")

    def generate(self, prompts: list[str]) -> list[str]:
        stop_sequences = self.kwargs.get("stop_sequences", [])
        max_new_tokens = self.kwargs.get("max_new_tokens", 400)
        results = []

        for prompt_text in prompts:
            inputs = self.tokenizer(prompt_text, return_tensors="pt").to(self.model.device)
            prompt_len = inputs["input_ids"].shape[1]

            stopping_criteria = StoppingCriteriaList([
                StopOnSequences(stop_sequences, self.tokenizer, prompt_len)
            ])

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    temperature=1.0,
                    eos_token_id=self.eos_ids,
                    pad_token_id=self.tokenizer.eos_token_id,
                    stopping_criteria=stopping_criteria,
                )

            generated = outputs[0][prompt_len:]
            answer = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
            results.append(answer)

        return results
