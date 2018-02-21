import argparse
import gym
import cv2
import os
import tensorflow as tf
import numpy as np
import box_constants
import atari_constants

from lightsaber.tensorflow.log import TfBoardLogger
from lightsaber.rl.explorer import LinearDecayExplorer, ConstantExplorer
from lightsaber.rl.replay_buffer import NECReplayBuffer
from lightsaber.rl.env_wrapper import EnvWrapper
from lightsaber.rl.trainer import Trainer

from actions import get_action_space
from network import make_network
from agent import Agent
from dnd import DND
from datetime import datetime
from env_wrapper import EnvWrapper
from tensorflow.python.client import timeline


run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
run_metadata = tf.RunMetadata()

def main():
    date = datetime.now().strftime("%Y%m%d%H%M%S")
    parser = argparse.ArgumentParser()
    parser.add_argument('--env', type=str, default='CartPole-v1')
    parser.add_argument('--outdir', type=str, default=date)
    parser.add_argument('--logdir', type=str, default=date)
    parser.add_argument('--gpu', type=int, default=0)
    parser.add_argument('--load', type=str, default=None)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()

    # learned model path settings
    outdir = os.path.join(os.path.dirname(__file__), 'results_' + args.outdir)
    if not os.path.exists(outdir):
        os.makedirs(outdir)
    # log path settings
    logdir = os.path.join(os.path.dirname(__file__), 'logs/' + args.logdir)

    env = gym.make(args.env)

    # box environment
    if len(env.observation_space.shape) == 1:
        constants = box_constants
        explorer = ConstantExplorer(constants.EXPLORATION_EPSILON)
        actions = range(env.action_space.n)
        state_shape = [env.observation_space.shape[0], constants.UPDATE_INTERVAL]
        state_preprocess = lambda state: state
        # (window_size, dim) -> (dim, window_size)
        phi = lambda state: np.transpose(state, [1, 0])
    # atari environment
    else:
        constants = atari_constants
        explorer = LinearDecayExplorer(
            final_exploration_step=constants.EXPLORATION_DURATION
        )
        actions = get_action_space(args.env)
        state_shape = [84, 84, constants.UPDATE_INTERVAL]
        def state_preprocess(state):
            state = cv2.cvtColor(state, cv2.COLOR_RGB2GRAY)
            state = cv2.resize(state, (84, 84))
            return np.array(state, dtype=np.float32) / 255.0
        # (window_size, H, W) -> (H, W, window_size)
        phi = lambda state: np.transpose(state, [1, 2, 0])

    # wrap gym environment
    env = EnvWrapper(
        env,
        s_preprocess=state_preprocess,
        r_preprocess=lambda r: np.clip(r, -1, 1)
    )

    # create encoder network
    network = make_network(
        constants.CONVS,
        constants.FCS,
        constants.DND_KEY_SIZE
    )

    replay_buffer = NECReplayBuffer(constants.REPLAY_BUFFER_SIZE)

    sess = tf.Session()
    sess.__enter__()

    # create DNDs
    dnds = []
    for i in range(len(actions)):
        dnd = DND(
            constants.DND_KEY_SIZE,
            constants.DND_CAPACITY,
            constants.DND_P
        )
        dnd._init_vars()
        dnds.append(dnd)

    # create NEC agent
    agent = Agent(
        network,
        dnds,
        actions,
        state_shape,
        replay_buffer,
        explorer,
        constants,
        phi=phi,
        run_options=run_options,
        run_metadata=run_metadata
    )

    sess.run(tf.global_variables_initializer())

    saver = tf.train.Saver()
    if args.load is not None:
        saver.restore(sess, args.load)

    # tensorboard logger
    train_writer = tf.summary.FileWriter(logdir, sess.graph)
    logger = TfBoardLogger(train_writer)
    logger.register('reward', dtype=tf.int32)
    end_episode = lambda r, t, e: logger.plot('reward', r, t)

    trainer = Trainer(
        env=env,
        agent=agent,
        render=args.render,
        state_shape=state_shape[:-1], # ignore last channel
        state_window=constants.UPDATE_INTERVAL,
        final_step=constants.FINAL_STEP,
        end_episode=end_episode,
        training=not args.demo
    )
    trainer.start()

if __name__ == '__main__':
    main()
