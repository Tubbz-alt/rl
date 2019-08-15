from gym_unity.envs import UnityEnv

from rl_main.conf.constants_mine import ENVIRONMENT_ID, PLATFORM, OSName
from rl_main.conf.names import EnvironmentName
from rl_main.environments.environment import Environment


class Chaser_v1(Environment):
    if PLATFORM == OSName.MAC:
        env_filename = EnvironmentName.CHASER_V1_MAC.value
    elif PLATFORM == OSName.WINDOWS:
        env_filename = EnvironmentName.CHASER_V1_WINDOWS.value
    else:
        env_filename = None

    unity_env_worker_id = 0

    def __init__(self):
        self.env = UnityEnv(
            environment_filename=ENVIRONMENT_ID.CHASER_V1.value,
            worker_id=Chaser_v1.unity_env_worker_id,
            use_visual=True,
            multiagent=True
        ).unwrapped
        self.increase_env_worker_id()
        super(Chaser_v1, self).__init__()
        self.action_shape = self.get_action_shape()
        self.state_shape = self.get_state_shape()

        self.cnn_input_height = self.state_shape[0]
        self.cnn_input_width = self.state_shape[1]
        self.cnn_input_channels = self.state_shape[2]

        self.continuous = True

    @staticmethod
    def increase_env_worker_id():
        Chaser_v1.unity_env_worker_id += 1

    def get_n_states(self):
        n_states = 3
        return n_states

    def get_n_actions(self):
        n_actions = 3
        return n_actions

    def get_state_shape(self):
        return self.env.observation_space.shape

    def get_action_shape(self):
        return self.env.action_space.shape

    def reset(self):
        state = self.env.reset()
        return state

    def step(self, action):
        next_state, reward, done, info = self.env.step(action)

        adjusted_reward = reward

        return next_state, reward, adjusted_reward, done, info

    def close(self):
        self.env.close()
