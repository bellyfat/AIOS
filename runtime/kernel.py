from typing_extensions import Literal
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import traceback
import json
import logging

from aios.hooks.modules.llm import useCore
from aios.hooks.modules.memory import useMemoryManager
from aios.hooks.modules.storage import useStorageManager
from aios.hooks.modules.tool import useToolManager
from aios.hooks.modules.agent import useFactory
from aios.hooks.modules.scheduler import fifo_scheduler_nonblock as fifo_scheduler
from aios.hooks.syscall import useSysCall

from cerebrum.llm.communication import LLMQuery

from fastapi.middleware.cors import CORSMiddleware

# from cerebrum.llm.layer import LLMLayer as LLMConfig
# from cerebrum.memory.layer import MemoryLayer as MemoryConfig
# from cerebrum.storage.layer import StorageLayer as StorageConfig
# from cerebrum.tool.layer import ToolLayer as ToolManagerConfig

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Modify this in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store component configurations and instances
active_components = {
    "llm": None,
    "storage": None,
    "memory": None,
    "tool": None,
    "scheduler": None,
}

send_request, SysCallWrapper = useSysCall()

# Configure the root logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Output to console
    ]
)

logger = logging.getLogger(__name__)

class LLMConfig(BaseModel):
    llm_name: str
    max_gpu_memory: dict | None = None
    eval_device: str = "cuda:0"
    max_new_tokens: int = 2048
    log_mode: str = "INFO"
    llm_backend: str = "default"
    api_key: str | None = None


class StorageConfig(BaseModel):
    root_dir: str = "root"
    use_vector_db: bool = False
    vector_db_config: Optional[Dict[str, Any]] = None


class MemoryConfig(BaseModel):
    memory_limit: int = 104857600  # 100MB in bytes
    eviction_k: int = 10
    custom_eviction_policy: Optional[str] = None


class ToolManagerConfig(BaseModel):
    allowed_tools: Optional[list[str]] = None
    custom_tools: Optional[Dict[str, Any]] = None


class SchedulerConfig(BaseModel):
    log_mode: str = "INFO"
    max_workers: int = 64
    custom_syscalls: Optional[Dict[str, Any]] = None


class SchedulerConfig(BaseModel):
    log_mode: str = "INFO"
    max_workers: int = 64
    custom_syscalls: Optional[Dict[str, Any]] = None


class AgentSubmit(BaseModel):
    agent_id: str
    agent_config: Dict[str, Any]


class QueryRequest(BaseModel):
    agent_name: str
    query_type: Literal["llm", "tool", "storage", "memory"]
    query_data: LLMQuery


@app.post("/core/llm/setup")
async def setup_llm(config: LLMConfig):
    """Set up the LLM core component."""
    try:
        llm = useCore(
            llm_name=config.llm_name,
            llm_backend=config.llm_backend,
            max_gpu_memory=config.max_gpu_memory,
            eval_device=config.eval_device,
            max_new_tokens=config.max_new_tokens,
            log_mode=config.log_mode,
        )
        # print(config.llm_name)
        active_components["llm"] = llm
        return {"status": "success", "message": "LLM core initialized"}
    except Exception as e:
        print(
            f"LLM setup failed: {str(e)}, please check whether you have set up the required LLM API key and whether the llm_name and llm_backend is correct."
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to initialize LLM core: {str(e)}"
        )


@app.post("/core/storage/setup")
async def setup_storage(config: StorageConfig):
    """Set up the storage manager component."""
    try:
        storage_manager = useStorageManager(
            root_dir=config.root_dir,
            use_vector_db=config.use_vector_db,
            **(config.vector_db_config or {}),
        )
        active_components["storage"] = storage_manager
        return {"status": "success", "message": "Storage manager initialized"}
    except Exception as e:
        print(f"Storage setup failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to initialize storage manager: {str(e)}"
        )


@app.post("/core/memory/setup")
async def setup_memory(config: MemoryConfig):
    """Set up the memory manager component."""
    if not active_components["storage"]:
        raise HTTPException(
            status_code=400, detail="Storage manager must be initialized first"
        )

    try:
        memory_manager = useMemoryManager(
            memory_limit=config.memory_limit,
            eviction_k=config.eviction_k,
            storage_manager=active_components["storage"],
        )
        active_components["memory"] = memory_manager
        return {"status": "success", "message": "Memory manager initialized"}
    except Exception as e:
        print(f"Memory setup failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to initialize memory manager: {str(e)}"
        )


@app.post("/core/tool/setup")
async def setup_tool_manager(config: ToolManagerConfig):
    """Set up the tool manager component."""
    try:
        print(f"\n[DEBUG] ===== Setting up Tool Manager =====")
        tool_manager = useToolManager()
        active_components["tool"] = tool_manager
        return {"status": "success", "message": "Tool manager initialized"}
    except Exception as e:
        error_msg = str(e)
        stack_trace = traceback.format_exc()
        print(f"[ERROR] Tool Manager Setup Failed: {error_msg}")
        print(f"[ERROR] Stack Trace:\n{stack_trace}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to initialize tool manager",
                "message": error_msg,
                "traceback": stack_trace
            }
        )


@app.post("/core/factory/setup")
async def setup_agent_factory(config: SchedulerConfig):
    """Set up the agent factory for managing agent execution."""
    required_components = ["llm", "memory", "storage", "tool"]
    missing_components = [
        comp for comp in required_components if not active_components[comp]
    ]

    if missing_components:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required components: {', '.join(missing_components)}",
        )

    try:
        submit_agent, await_agent_execution = useFactory(
            log_mode=config.log_mode, max_workers=config.max_workers
        )

        active_components["factory"] = {
            "submit": submit_agent,
            "await": await_agent_execution,
        }

        print(active_components["llm"].model)

        return {"status": "success", "message": "Agent factory initialized"}
    except Exception as e:
        print(f"Agent factory setup failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to initialize agent factory: {str(e)}"
        )


@app.post("/core/scheduler/setup")
async def setup_scheduler(config: SchedulerConfig):
    """Set up the FIFO scheduler with all components."""
    required_components = ["llm", "memory", "storage", "tool"]
    missing_components = [
        comp for comp in required_components if not active_components[comp]
    ]

    if missing_components:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required components: {', '.join(missing_components)}",
        )

    try:
        # Set up the scheduler with all components
        scheduler = fifo_scheduler(
            llm=active_components["llm"],   
            memory_manager=active_components["memory"],
            storage_manager=active_components["storage"],
            tool_manager=active_components["tool"],
            log_mode=config.log_mode,
            get_llm_syscall=None,
            get_memory_syscall=None,
            get_storage_syscall=None,
            get_tool_syscall=None,
        )

        active_components["scheduler"] = scheduler

        scheduler.start()

        return {"status": "success", "message": "Scheduler initialized"}
    except Exception as e:
        print(f"Scheduler setup failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to initialize scheduler: {str(e)}"
        )


@app.get("/core/status")
async def get_status():
    """Get the status of all core components."""
    return {
        component: "active" if instance else "inactive"
        for component, instance in active_components.items()
    }


@app.post("/agents/submit")
async def submit_agent(config: AgentSubmit):
    """Submit an agent for execution using the agent factory."""
    if "factory" not in active_components or not active_components["factory"]:
        raise HTTPException(status_code=400, detail="Agent factory not initialized")

    try:
        print(f"\n[DEBUG] ===== Agent Submission =====")
        print(f"[DEBUG] Agent ID: {config.agent_id}")
        print(f"[DEBUG] Task: {config.agent_config.get('task', 'No task specified')}")
        
        _submit_agent = active_components["factory"]["submit"]
        execution_id = _submit_agent(
            agent_name=config.agent_id, task_input=config.agent_config["task"]
        )
        
        return {
            "status": "success",
            "execution_id": execution_id,
            "message": f"Agent {config.agent_id} submitted for execution"
        }
    except Exception as e:
        error_msg = str(e)
        stack_trace = traceback.format_exc()
        print(f"[ERROR] Agent submission failed: {error_msg}")
        print(f"[ERROR] Stack Trace:\n{stack_trace}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to submit agent",
                "message": error_msg,
                "traceback": stack_trace
            }
        )


@app.get("/agents/{execution_id}/status")
async def get_agent_status(execution_id: int):
    """Get the status of a submitted agent."""
    if "factory" not in active_components or not active_components["factory"]:
        raise HTTPException(status_code=400, detail="Agent factory not initialized")

    try:
        logger.debug(f"\n===== Checking Agent Status =====")
        logger.debug(f"Execution ID: {execution_id}")
        
        await_execution = active_components["factory"]["await"]
        
        try:
            result = await_execution(int(execution_id))
            logger.debug(f"Execution result: {result}")
            
            if result is None:
                return {
                    "status": "running",
                    "message": "Execution in progress",
                    "execution_id": execution_id,
                    "debug_info": "Agent execution still in progress"
                }

            return {
                "status": "completed",
                "result": result,
                "execution_id": execution_id
            }
        except Exception as inner_e:
            logger.error(f"Error in execution: {str(inner_e)}")
            logger.error(f"Inner stack trace:\n{traceback.format_exc()}")
            raise
            
    except Exception as e:
        error_msg = str(e)
        stack_trace = traceback.format_exc()
        logger.error(f"Failed to get agent status: {error_msg}")
        logger.error(f"Stack Trace:\n{stack_trace}")
        
        # Return more detailed error information
        return {
            "status": "error",
            "message": error_msg,
            "error": {
                "type": type(e).__name__,
                "message": error_msg,
                "traceback": stack_trace,
                "debug_logs": getattr(e, 'debug_logs', None)
            },
            "execution_id": execution_id
        }


@app.post("/core/cleanup")
async def cleanup_components():
    """Clean up all active components."""
    try:
        # Clean up in reverse order of dependency
        active_components["scheduler"].stop()
        active_components["scheduler"] = None

        for component in ["tool", "memory", "storage", "llm"]:
            if active_components[component]:
                if hasattr(active_components[component], "cleanup"):
                    active_components[component].cleanup()
                active_components[component] = None

        return {"status": "success", "message": "All components cleaned up"}
    except Exception as e:
        # print(e)
        print(f"Failed to cleanup components: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to cleanup components: {str(e)}"
        )


@app.post("/query")
async def handle_query(request: QueryRequest):
    try:
        if request.query_type == "llm":
            query = LLMQuery(
                messages=request.query_data.messages,
                tools=request.query_data.tools,
                action_type=request.query_data.action_type,
                message_return_type=request.query_data.message_return_type,
            )
            return send_request(request.agent_name, query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))