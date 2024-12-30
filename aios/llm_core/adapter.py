
from typing import Dict, Optional
from aios.llm_core.cores.base import BaseLLM
from aios.llm_core.registry import BACKEND_REGISTRY, MODEL_PREFIX_MAP
from aios.llm_core.cores.local.hf import HfNativeLLM

class LLMAdapter:
    """Parameters for LLMs

    Args:
        llm_name (str): Name of the LLMs
        max_gpu_memory (dict, optional): Maximum GPU resources that can be allocated to the LLM. Defaults to None.
        eval_device (str, optional): Evaluation device of binding LLM to designated devices for inference. Defaults to None.
        max_new_tokens (int, optional): Maximum token length generated by the LLM. Defaults to 256.
        log_mode (str, optional): Mode of logging the LLM processing status. Defaults to "console".
        llm_backend (str, optional): Backend to use for speeding up open-source LLMs. Defaults to None. Choices are ["vllm", "ollama"]
    """

    def __init__(
        self,
        llm_name: str,
        max_gpu_memory: Optional[Dict] = None,
        eval_device: Optional[str] = None,
        max_new_tokens: int = 256,
        log_mode: str = "console",
        llm_backend: Optional[str] = None,
        use_context_manager: bool = False,
        api_key: str = None
    ):
        """Initialize the LLM with the specified configuration.
        
        Args:
            llm_name: Name of the LLM model to use
            max_gpu_memory: Maximum GPU memory allocation per device
            eval_device: Device to use for evaluation
            max_new_tokens: Maximum number of new tokens to generate
            log_mode: Logging mode ("console" or other options)
            use_backend: Specific backend to use (if None, inferred from model name)
            use_context_manager: Whether to use context manager
            api_key: API Key for the LLM
        """
        self.model: Optional[BaseLLM] = None
        
        # Common model parameters
        model_params = {
            'llm_name': llm_name,
            'log_mode': log_mode,
            'use_context_manager': use_context_manager,
            'api_key': api_key
        }
        
        # print(llm_name)
        # print(llm_backend)
        
        # print(llm_name)
        
        # If backend is explicitly specified, use it
        # print(f"llm backend: {llm_backend}")
        if llm_backend and llm_backend in BACKEND_REGISTRY:
            model_class = BACKEND_REGISTRY[llm_backend]
            self.model = model_class(**model_params)
            # print(self.model)
            return

        # Try to infer backend from model name prefix
        model_prefix = next(
            (prefix for prefix in MODEL_PREFIX_MAP.keys() 
            if llm_name.lower().startswith(prefix)),
            None
        )
        
        # print(model_prefix)
        
        if model_prefix:
            inferred_backend = MODEL_PREFIX_MAP[model_prefix]
            model_class = BACKEND_REGISTRY[inferred_backend]
            self.model = model_class(**model_params)
            return
        
        # print("Here")
        # Default to HuggingFace native implementation if no specific backend is found
        self.model = HfNativeLLM(**model_params)

    def address_syscall(self,
                        llm_syscall,
                        temperature=0.0) -> None:
        """Address request sent from the agent

        Args:
            agent_request: AgentProcess object that contains request sent from the agent
            temperature (float, optional): Parameter to control the randomness of LLM output. Defaults to 0.0.
        """
        return self.model.address_syscall(llm_syscall, temperature)


    