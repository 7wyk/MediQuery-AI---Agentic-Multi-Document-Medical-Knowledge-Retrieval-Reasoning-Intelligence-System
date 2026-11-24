import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import authService, { User } from '../services/auth.service';
import { SessionError } from '../lib/authErrors';

interface AuthContextType {
    user: User | null;
    loading: boolean;
    login: (email: string, password: string) => Promise<void>;
    logout: () => void;
    isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        // Check if user is authenticated on mount
        let cancelled = false;

        const initAuth = async () => {
            if (authService.isAuthenticated()) {
                try {
                    const currentUser = await authService.getCurrentUser();
                    if (!cancelled) setUser(currentUser);
                } catch (error) {
                    console.warn('[auth] stored session is no longer valid:', error);
                    authService.logout();
                }
            }
            if (!cancelled) setLoading(false);
        };

        initAuth();

        return () => {
            cancelled = true;
        };
    }, []);

    const login = async (email: string, password: string) => {
        // Trim the address only; the password is sent exactly as typed.
        await authService.login({ email: email.trim(), password });

        try {
            const currentUser = await authService.getCurrentUser();
            setUser(currentUser);
        } catch (error) {
            // Tokens were issued but the profile could not be loaded, so the
            // session is unusable: drop it rather than leave a half-signed-in state.
            console.warn('[auth] issued tokens could not be used to load the profile:', error);
            authService.logout();
            setUser(null);
            throw new SessionError();
        }
    };

    const logout = () => {
        authService.logout();
        setUser(null);
    };

    const value = {
        user,
        loading,
        login,
        logout,
        isAuthenticated: !!user,
    };

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};
