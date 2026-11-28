import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    COURSE_MAX_POINTS, courseLegs, courseable, effectiveLook, numberDirection, shortenLeg, startTriangle,
} from '../../frontend/js/course.js';

// Same cases as tests/test_course_geometry.py: both sides draw the same course
const close = (p, q) => Math.abs(p[0] - q[0]) < 1e-9 && Math.abs(p[1] - q[1]) < 1e-9;

test('shortenLeg cuts each end by its radius', () => {
    const [a, b] = shortenLeg([0, 0], [10, 0], 1, 2);
    assert.ok(close(a, [1, 0]) && close(b, [8, 0]));
});

test('shortenLeg: a leg shorter than both radii is null', () => {
    assert.equal(shortenLeg([0, 0], [3, 0], 1, 2), null);
    assert.equal(shortenLeg([5, 5], [5, 5], 1, 1), null);   // start == finish
});

test('courseLegs uses start, control and finish radii plus the gap', () => {
    const legs = courseLegs([[0, 0], [100, 0], [100, 100]], { start: 4, control: 3, finish: 3.5, gap: 0.5 });
    assert.equal(legs.length, 2);
    assert.ok(close(legs[0][0], [4.5, 0]) && close(legs[0][1], [96.5, 0]));
    assert.ok(close(legs[1][0], [100, 3.5]) && close(legs[1][1], [100, 96]));
});

test('courseLegs skips a leg that is too short', () => {
    const legs = courseLegs([[0, 0], [1, 0], [100, 0]], { start: 4, control: 3, finish: 3.5, gap: 0 });
    assert.equal(legs.length, 1);
    assert.ok(close(legs[0][0], [4, 0]));
});

test('numberDirection points away from both legs', () => {
    assert.ok(close(numberDirection([-1, 0], [0, 0], [0, 1]), [Math.SQRT1_2, -Math.SQRT1_2]));
});

test('numberDirection: straight through goes to the left', () => {
    assert.ok(close(numberDirection([-1, 0], [0, 0], [1, 0]), [0, 1]));
});

test('numberDirection: all points the same is still a unit vector', () => {
    const [x, y] = numberDirection([0, 0], [0, 0], [0, 0]);
    assert.ok(Math.abs(x * x + y * y - 1) < 1e-9);
});

test('startTriangle points its first corner at the first control', () => {
    const t = startTriangle([0, 0], [10, 0], Math.sqrt(3));   // circumradius 1
    assert.ok(close(t[0], [1, 0]));
    assert.ok(close(t[1], [-0.5, Math.sqrt(3) / 2]) && close(t[2], [-0.5, -Math.sqrt(3) / 2]));
});

const pts = n => Array.from({ length: n }, (_, i) => [i, i]);

test('courseable: one line of 2..100 points that is not a track', () => {
    assert.equal(COURSE_MAX_POINTS, 100);
    assert.equal(courseable({ source: 'drawn', lines: [pts(2)] }), true);
    assert.equal(courseable({ source: 'rte', lines: [pts(5)] }), true);
    assert.equal(courseable({ source: 'wpt', lines: [pts(5)] }), true);
    assert.equal(courseable({ source: 'drawn', lines: [pts(100)] }), true);
    assert.equal(courseable({ source: 'drawn', lines: [pts(101)] }), false);
    assert.equal(courseable({ source: 'trk', lines: [pts(5)] }), false);
    assert.equal(courseable({ source: 'drawn', lines: [pts(3), pts(3)] }), false);
    assert.equal(courseable({ source: 'drawn', lines: [pts(1)] }), false);
    assert.equal(courseable({ source: 'drawn', lines: [] }), false);
});

test('effectiveLook falls back to line when the route cannot be a course', () => {
    const drawn = { source: 'drawn', lines: [pts(3)] };
    const track = { source: 'trk', lines: [pts(3)] };
    assert.equal(effectiveLook('course', drawn), 'course');
    assert.equal(effectiveLook('course', track), 'line');
    assert.equal(effectiveLook('line', drawn), 'line');
});
