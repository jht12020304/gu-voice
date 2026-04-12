// =============================================================================
// 使用者管理頁（管理員）
// =============================================================================

import { useEffect, useState, useCallback } from 'react';
import SearchBar from '../../components/form/SearchBar';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import Modal from '../../components/common/Modal';
import * as adminApi from '../../services/api/admin';
import type { User } from '../../types';
import { formatDate } from '../../utils/format';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockUsers: User[] = [
  { id: 'u1', email: 'doctor@gu-voice.local', name: '王大明', role: 'doctor', phone: '0912-345-678', department: '泌尿科', isActive: true, lastLoginAt: '2026-04-10T08:00:00Z', createdAt: '2024-01-01T00:00:00Z', updatedAt: '2026-04-10T08:00:00Z' },
  { id: 'u2', email: 'admin@gu-voice.local', name: '系統管理員', role: 'admin', isActive: true, lastLoginAt: '2026-04-10T07:30:00Z', createdAt: '2024-01-01T00:00:00Z', updatedAt: '2026-04-10T07:30:00Z' },
  { id: 'u3', email: 'chen@example.com', name: '陳小明', role: 'patient', phone: '0912-345-678', isActive: true, lastLoginAt: '2026-04-10T13:30:00Z', createdAt: '2026-01-15T08:00:00Z', updatedAt: '2026-04-10T13:30:00Z' },
  { id: 'u4', email: 'lin@example.com', name: '林美玲', role: 'patient', phone: '0923-456-789', isActive: true, lastLoginAt: '2026-04-09T10:00:00Z', createdAt: '2026-02-03T09:30:00Z', updatedAt: '2026-04-09T10:00:00Z' },
  { id: 'u5', email: 'chang@example.com', name: '張大偉', role: 'patient', phone: '0934-567-890', isActive: false, lastLoginAt: '2026-03-20T14:00:00Z', createdAt: '2026-02-10T14:00:00Z', updatedAt: '2026-03-20T14:00:00Z' },
  { id: 'u6', email: 'doctor2@gu-voice.local', name: '李醫師', role: 'doctor', phone: '0956-789-012', department: '泌尿科', isActive: true, lastLoginAt: '2026-04-10T09:00:00Z', createdAt: '2024-06-01T00:00:00Z', updatedAt: '2026-04-10T09:00:00Z' },
];

const ROLE_TABS = [
  { key: '', label: '全部' },
  { key: 'patient', label: '病患' },
  { key: 'doctor', label: '醫師' },
  { key: 'admin', label: '管理員' },
];

const roleLabels: Record<string, string> = {
  patient: '病患',
  doctor: '醫師',
  admin: '管理員',
};

export default function UserManagementPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);

  // 表單狀態
  const [formData, setFormData] = useState({
    email: '',
    name: '',
    password: '',
    role: 'patient' as 'patient' | 'doctor' | 'admin',
    phone: '',
    isActive: true,
  });
  const [formError, setFormError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchUsers = useCallback(async () => {
    if (IS_MOCK) {
      let filtered = mockUsers;
      if (roleFilter) filtered = filtered.filter((u) => u.role === roleFilter);
      if (searchQuery) filtered = filtered.filter((u) => u.name.includes(searchQuery) || u.email.includes(searchQuery));
      setUsers(filtered);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    try {
      const response = await adminApi.getUsers({
        search: searchQuery || undefined,
        role: roleFilter || undefined,
        limit: 50,
      });
      setUsers(response.data);
    } catch {
      // 靜默
    } finally {
      setIsLoading(false);
    }
  }, [searchQuery, roleFilter]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleSearch = (query: string) => {
    setSearchQuery(query);
  };

  const openCreateModal = () => {
    setEditingUser(null);
    setFormData({ email: '', name: '', password: '', role: 'patient', phone: '', isActive: true });
    setFormError('');
    setShowCreateModal(true);
  };

  const openEditModal = (user: User) => {
    setEditingUser(user);
    setFormData({
      email: user.email,
      name: user.name,
      password: '',
      role: user.role,
      phone: user.phone || '',
      isActive: user.isActive,
    });
    setFormError('');
    setShowCreateModal(true);
  };

  const handleSubmit = async () => {
    setFormError('');
    if (!formData.name.trim() || !formData.email.trim()) {
      setFormError('姓名與電子郵件為必填');
      return;
    }

    setIsSubmitting(true);
    try {
      if (editingUser) {
        await adminApi.updateUser(editingUser.id, {
          name: formData.name,
          email: formData.email,
          phone: formData.phone || undefined,
          role: formData.role,
          isActive: formData.isActive,
        });
      } else {
        if (!formData.password) {
          setFormError('請輸入密碼');
          setIsSubmitting(false);
          return;
        }
        await adminApi.createUser({
          email: formData.email,
          name: formData.name,
          password: formData.password,
          role: formData.role,
          phone: formData.phone || undefined,
          isActive: formData.isActive,
        });
      }
      setShowCreateModal(false);
      fetchUsers();
    } catch {
      setFormError('操作失敗，請稍後再試');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleToggleActive = async (user: User) => {
    if (IS_MOCK) {
      setUsers((prev) => prev.map((u) => u.id === user.id ? { ...u, isActive: !u.isActive } : u));
      return;
    }
    try {
      await adminApi.toggleUserActive(user.id);
      fetchUsers();
    } catch {
      // 靜默
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <h1 className="text-h1 text-ink-heading dark:text-white">使用者管理</h1>
        <button className="btn-primary" onClick={openCreateModal}>
          <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          新增使用者
        </button>
      </div>

      {/* 篩選 */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="w-64">
          <SearchBar value={searchQuery} onChange={handleSearch} placeholder="搜尋姓名或 Email..." />
        </div>
        <div className="flex gap-2">
          {ROLE_TABS.map((tab) => (
            <button
              key={tab.key}
              className={`rounded-btn px-3 py-1.5 text-caption font-medium transition-colors ${
                roleFilter === tab.key
                  ? 'bg-primary-600 text-white'
                  : 'bg-white text-ink-secondary border border-edge hover:bg-surface-tertiary dark:bg-dark-card dark:border-dark-border dark:text-ink-muted'
              }`}
              onClick={() => setRoleFilter(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* 表格 */}
      {isLoading ? (
        <LoadingSpinner fullPage />
      ) : users.length === 0 ? (
        <EmptyState title="無使用者" message="目前沒有符合條件的使用者" />
      ) : (
        <div className="card overflow-hidden p-0">
          <table className="w-full">
            <thead>
              <tr className="table-header">
                <th className="px-6 py-3 text-left">使用者</th>
                <th className="px-6 py-3 text-left">角色</th>
                <th className="px-6 py-3 text-left">狀態</th>
                <th className="px-6 py-3 text-left">最後登入</th>
                <th className="px-6 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="table-row">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary-50 text-small font-semibold text-primary-700 dark:bg-primary-950 dark:text-primary-300">
                        {user.name.charAt(0)}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-body font-medium text-ink-heading dark:text-white">{user.name}</p>
                        <p className="truncate text-small text-ink-muted">{user.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="badge badge-waiting">
                      {roleLabels[user.role] || user.role}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-pill px-2.5 py-0.5 text-small font-medium ${
                        user.isActive
                          ? 'bg-alert-success-bg text-alert-success-text'
                          : 'bg-status-cancelled-bg text-status-cancelled'
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          user.isActive ? 'bg-alert-success' : 'bg-status-cancelled'
                        }`}
                      />
                      {user.isActive ? '啟用' : '停用'}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-body text-ink-muted font-tnum">
                    {formatDate(user.lastLoginAt, {
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        className="rounded-btn px-2.5 py-1 text-small font-medium text-primary-600 hover:bg-primary-50 transition-colors"
                        onClick={() => openEditModal(user)}
                      >
                        編輯
                      </button>
                      <button
                        className={`rounded-btn px-2.5 py-1 text-small font-medium transition-colors ${
                          user.isActive
                            ? 'text-alert-critical hover:bg-alert-critical-bg'
                            : 'text-alert-success hover:bg-alert-success-bg'
                        }`}
                        onClick={() => handleToggleActive(user)}
                      >
                        {user.isActive ? '停用' : '啟用'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 新增/編輯 Modal */}
      <Modal
        visible={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        title={editingUser ? '編輯使用者' : '新增使用者'}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setShowCreateModal(false)}>
              取消
            </button>
            <button
              className="btn-primary"
              onClick={handleSubmit}
              disabled={isSubmitting}
            >
              {isSubmitting ? '處理中...' : editingUser ? '更新' : '建立'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {formError && (
            <div className="rounded-card bg-alert-critical-bg border border-alert-critical-border p-3 text-body text-alert-critical-text">
              {formError}
            </div>
          )}

          <div>
            <label className="block text-caption font-medium text-ink-body">姓名 *</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="input-base mt-1"
            />
          </div>

          <div>
            <label className="block text-caption font-medium text-ink-body">電子郵件 *</label>
            <input
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              className="input-base mt-1"
            />
          </div>

          {!editingUser && (
            <div>
              <label className="block text-caption font-medium text-ink-body">密碼 *</label>
              <input
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                className="input-base mt-1"
              />
            </div>
          )}

          <div>
            <label className="block text-caption font-medium text-ink-body">角色</label>
            <select
              value={formData.role}
              onChange={(e) =>
                setFormData({ ...formData, role: e.target.value as 'patient' | 'doctor' | 'admin' })
              }
              className="input-base mt-1"
            >
              <option value="patient">病患</option>
              <option value="doctor">醫師</option>
              <option value="admin">管理員</option>
            </select>
          </div>

          <div>
            <label className="block text-caption font-medium text-ink-body">手機號碼</label>
            <input
              type="tel"
              value={formData.phone}
              onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
              placeholder="0912345678"
              className="input-base mt-1"
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="isActive"
              checked={formData.isActive}
              onChange={(e) => setFormData({ ...formData, isActive: e.target.checked })}
              className="h-4 w-4 rounded-btn border-edge text-primary-600 focus:ring-primary-500"
            />
            <label htmlFor="isActive" className="text-body text-ink-body">
              帳號啟用
            </label>
          </div>
        </div>
      </Modal>
    </div>
  );
}
